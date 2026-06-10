"""API路由 - 所有JSON API端点"""

import json
import os
import sys
from datetime import datetime
from fastapi import APIRouter, Request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_connection, get_latest_draw, get_all_latest_draws
from app.fetcher import fetch_data
from app.parser import parse_line
from app.stats_service import search_by_number, get_history_detail, advanced_search as advanced_search_fn
from app.stats_builder import build_number_stats, get_all_number_stats
from app.unused import get_unused_numbers
from app.auto_updater import catch_up_missing, do_json_update
from app.cache import (cached, delete as cache_delete, clear as cache_clear,
                       get_manual_update_cooldown, set_manual_update_timestamp,
                       can_manual_update)
from app.config import CACHE_SYSTEM_STATS_TTL, CACHE_COUNTDOWN_TTL, CACHE_SYSTEM_STATUS_TTL, POLL_START_HOUR, POLL_END_HOUR

router = APIRouter()


def get_all_types():
    """获取所有彩票类型"""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT * FROM lottery_types WHERE active=1 ORDER BY sort_order"
    )
    types = [dict(row) for row in cursor.fetchall()]
    for t in types:
        if t.get("prize_levels"):
            t["prize_levels"] = json.loads(t["prize_levels"])
    conn.close()
    return types


def parse_draw_json(draw):
    """解析开奖数据的JSON字段"""
    if not draw:
        return draw
    draw = dict(draw)
    for key in ["numbers", "prizes", "trial_numbers", "machine_ball", "draw_order"]:
        if draw.get(key):
            try:
                draw[key] = json.loads(draw[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return draw


# ============================================================
# 彩种 & 开奖数据
# ============================================================

@router.get("/types")
async def api_types():
    return get_all_types()


def _get_draws(lottery_code, limit=50, offset=0, start_date="", end_date=""):
    """内部：获取某彩票的历史开奖数据"""
    conn = get_connection()
    cursor = conn.cursor()
    where = "lottery_code=?"
    params = [lottery_code]
    if start_date:
        where += " AND draw_date >= ?"
        params.append(start_date)
    if end_date:
        where += " AND draw_date <= ?"
        params.append(end_date)
    cursor.execute(
        f"SELECT * FROM lottery_draws WHERE {where} ORDER BY draw_number DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.execute(f"SELECT COUNT(*) as total FROM lottery_draws WHERE {where}", params)
    total = cursor.fetchone()["total"]
    conn.close()
    for row in rows:
        for key in ["numbers", "trial_numbers", "machine_ball", "draw_order", "prizes", "extra"]:
            if row.get(key):
                try:
                    row[key] = json.loads(row[key])
                except (json.JSONDecodeError, TypeError):
                    pass
    return rows, total


@router.get("/draws/{lottery_code}")
async def api_draws(
    lottery_code: str,
    limit: int = 50,
    offset: int = 0,
    start_date: str = "",
    end_date: str = "",
):
    draws, total = _get_draws(lottery_code, limit, offset, start_date, end_date)
    return {"data": draws, "total": total, "limit": limit, "offset": offset}


@router.get("/latest")
async def api_latest_all():
    """获取所有彩种最新开奖数据（已优化为批量查询）"""
    types = get_all_types()
    conn = get_connection()
    codes = [t["code"] for t in types]
    latest_draws = get_all_latest_draws(conn, codes)
    conn.close()
    result = []
    for t in types:
        draw = latest_draws.get(t["code"])
        if draw:
            draw = parse_draw_json(draw)
            result.append({"type": {"code": t["code"], "name": t["name"], "full_name": t["full_name"]}, "draw": draw})
    return {"data": result, "total": len(result)}


@router.get("/{lottery_code}/latest")
async def api_latest_code(lottery_code: str):
    """获取单个彩种最新开奖"""
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}
    conn = get_connection()
    draw = get_latest_draw(conn, lottery_code)
    conn.close()
    if not draw:
        return {"status": "error", "message": "暂无数据"}
    return {"status": "success", "data": parse_draw_json(draw)}


# ============================================================
# 搜索 & 统计
# ============================================================

@router.get("/{lottery_code}/search-number")
async def api_search_number(
    lottery_code: str,
    q: str = "",
    search_type: str = "group",
    page: int = 1,
):
    results, total, count_info = search_by_number(lottery_code, q, search_type, page, 30)
    return {"data": results, "total": total, "count_info": count_info}


@router.get("/{lottery_code}/history-detail")
async def api_history_detail(
    lottery_code: str,
    q: str = "",
    search_type: str = "group",
    page: int = 1,
):
    periods, total = get_history_detail(lottery_code, q, search_type, page, 50)
    return {"data": periods, "total": total}


@router.get("/{lottery_code}/number-stats")
async def api_number_stats_page(lottery_code: str, page: int = 1):
    data = get_all_number_stats(lottery_code, page=page, page_size=100)
    return {"status": "success", **data}


@router.get("/{lottery_code}/batch-number-stats")
async def api_batch_number_stats(lottery_code: str, numbers: str = ""):
    """批量查询多个号码的直选和组选出现次数
    
    numbers: 逗号分隔的号码列表，如 '111,222,333'
    """
    if not numbers:
        return {"status": "error", "message": "请提供要查询的号码列表"}
    
    num_list = [n.strip() for n in numbers.split(",") if n.strip()]
    if not num_list:
        return {"status": "error", "message": "号码列表为空"}
    
    conn = get_connection()
    cursor = conn.cursor()
    
    results = []
    for num in num_list:
        # 直选统计
        cursor.execute(
            "SELECT appear_count FROM number_stats WHERE lottery_code=? AND number_text=? AND stat_type='direct'",
            (lottery_code, num)
        )
        direct_row = cursor.fetchone()
        direct_count = direct_row["appear_count"] if direct_row else 0
        
        # 组选统计（对数字排序后查询）
        from app.matcher import SINGLE_DIGIT_TYPES
        if lottery_code in SINGLE_DIGIT_TYPES:
            sorted_digits = sorted(num)
            group_key = "".join(sorted_digits)
        else:
            group_key = num
        
        cursor.execute(
            "SELECT appear_count FROM number_stats WHERE lottery_code=? AND number_text=? AND stat_type='group'",
            (lottery_code, group_key)
        )
        group_row = cursor.fetchone()
        group_count = group_row["appear_count"] if group_row else 0
        
        results.append({
            "number": num,
            "direct_count": direct_count,
            "group_count": group_count,
        })
    
    conn.close()
    return {"status": "success", "data": results}


@router.get("/{lottery_code}/unused-numbers")
async def api_unused_numbers(lottery_code: str, page: int = 1, year_range: str = "all",
                             date_from: str = "", date_to: str = ""):
    data = get_unused_numbers(lottery_code, page=page, page_size=200,
                              year_range=year_range, date_from=date_from, date_to=date_to)
    if data is None:
        return {"status": "error", "message": "该彩种不支持未开奖号码查询"}
    return {"status": "success", **data}


@router.get("/{lottery_code}/number-history")
async def api_number_history(
    lottery_code: str,
    q: str = "",
    num_type: str = "single",
):
    """查询指定号码在各历史时间段是否开出及出现次数"""
    from app.unused import check_number_history

    if not q or not q.strip():
        return {"status": "error", "message": "请提供查询号码"}
    result = check_number_history(lottery_code, q.strip(), num_type)
    if not result["periods"]:
        return {"status": "error", "message": "查询失败，请检查号码格式"}
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/today-history")
async def api_today_history(
    lottery_code: str,
    date: str = "",
    draw_number: str = "",
):
    """获取历史的今天开奖数据"""
    from app.unused import get_today_history, get_draw_by_number

    if draw_number:
        draw = get_draw_by_number(lottery_code, draw_number)
        if not draw:
            return {"status": "error", "message": "未找到该期号"}
        return {"status": "success", "data": {"draws": [draw], "current_date": draw["draw_date"]}}
    else:
        result = get_today_history(lottery_code, date or None)
        return {"status": "success", "data": result}


# ============================================================
# 数据导出
# ============================================================

# 简单的每日下载限制追踪（内存）
_download_tracker = {}  # {date: {client_key: set(export_types)}}

def _check_download_limit(request, lottery_code, export_type):
    """检查每日下载限制，返回 (allowed: bool, reason: str)"""
    from datetime import date
    today = date.today().isoformat()
    # 客户端标识：优先用cookie中的client_id，否则用IP
    client_id = request.cookies.get("dl_client_id", "")
    if not client_id:
        # 从X-Forwarded-For或remote_addr获取
        forwarded = request.headers.get("x-forwarded-for", "")
        client_id = forwarded.split(",")[0].strip() if forwarded else request.client.host if hasattr(request, 'client') and request.client else "unknown"

    key = f"{client_id}_{lottery_code}_{export_type}"

    # 初始化今日追踪
    if today not in _download_tracker:
        _download_tracker.clear()
        _download_tracker[today] = {}

    # 检查是否已下载过
    if key in _download_tracker[today]:
        return False, "每日每种数据仅限下载一次"

    # 记录下载
    _download_tracker[today][key] = True
    return True, ""


@router.get("/{lottery_code}/export")
async def api_export(
    request: Request,
    lottery_code: str,
    export_type: str = "",
    q: str = "",
    search_type: str = "group",
    date_from: str = "",
    date_to: str = "",
    draw_from: str = "",
    draw_to: str = "",
    period: str = "all",
):
    """导出数据为CSV格式"""
    from fastapi.responses import PlainTextResponse
    import csv, io, json
    from app.unused import get_period_draws
    from app.stats_service import search_by_number

    # 检查下载限制
    allowed, reason = _check_download_limit(request, lottery_code, export_type)
    if not allowed:
        return {"status": "error", "message": reason}

    output = io.StringIO()
    writer = csv.writer(output)

    def _safe_val(val):
        if val is None:
            return ""
        if isinstance(val, (list, dict)):
            try:
                return json.dumps(val, ensure_ascii=False)
            except:
                return str(val)
        return str(val)

    def _format_prizes(prizes):
        if not prizes:
            return ""
        if isinstance(prizes, str):
            try: prizes = json.loads(prizes)
            except: return prizes
        if isinstance(prizes, list):
            parts = []
            for p in prizes:
                if isinstance(p, dict):
                    parts.append(f"{p.get('level','')}:{p.get('count',0)}注/{p.get('amount',0)}元")
                else:
                    parts.append(str(p))
            return "; ".join(parts)
        return str(prizes)

    if export_type == "search" and q:
        results, total, _ = search_by_number(lottery_code, q, search_type, 1, 99999)
        writer.writerow(["期号", "开奖日期", "开奖号码", "匹配类型", "试机号", "机球号", "投注总额", "奖池金额", "奖金详情"])
        for row in results:
            nums_str = _format_numbers_for_csv(row.get("numbers", ""))
            is_direct = "直选" if row.get("is_direct") else "组选"
            trial = _safe_val(row.get("trial_numbers", ""))
            machine = _safe_val(row.get("machine_ball", ""))
            sale = _safe_val(row.get("sale_amount", ""))
            pool = _safe_val(row.get("prize_pool", ""))
            prizes = _format_prizes(row.get("prizes", ""))
            writer.writerow([row["draw_number"], row["draw_date"], nums_str, is_direct, trial, machine, sale, pool, prizes])

    elif export_type == "draws":
        results, total = _get_draws(lottery_code, limit=99999, offset=0,
                                     start_date=date_from, end_date=date_to)
        writer.writerow(["期号", "开奖日期", "开奖号码", "试机号", "机球号", "投注总额", "奖池金额", "奖金详情"])
        for row in results:
            nums_str = _format_numbers_for_csv(row.get("numbers", ""))
            trial = _safe_val(row.get("trial_numbers", ""))
            machine = _safe_val(row.get("machine_ball", ""))
            sale = _safe_val(row.get("sale_amount", ""))
            pool = _safe_val(row.get("prize_pool", ""))
            prizes = _format_prizes(row.get("prizes", ""))
            writer.writerow([row["draw_number"], row["draw_date"], nums_str, trial, machine, sale, pool, prizes])

    elif export_type == "period":
        data = get_period_draws(lottery_code, period_key=period,
                                 date_from=date_from, date_to=date_to,
                                 draw_from=draw_from, draw_to=draw_to,
                                 page=1, page_size=99999)
        writer.writerow(["期号", "开奖日期", "开奖号码", "试机号", "机球号", "投注总额", "奖池金额", "奖金详情"])
        for row in data.get("draws", []):
            nums_str = _format_numbers_for_csv(row.get("numbers", ""))
            trial = _safe_val(row.get("trial_numbers", ""))
            machine = _safe_val(row.get("machine_ball", ""))
            sale = _safe_val(row.get("sale_amount", ""))
            pool = _safe_val(row.get("prize_pool", ""))
            prizes = _format_prizes(row.get("prizes", ""))
            writer.writerow([row["draw_number"], row["draw_date"], nums_str, trial, machine, sale, pool, prizes])

    elif export_type == "today" and (q or date_from or date_to):
        from app.unused import get_today_history, get_draw_by_number
        draws = []
        if q:
            draw = get_draw_by_number(lottery_code, q)
            if draw:
                draws = [draw]
            else:
                return {"status": "error", "message": "未找到该期号"}
        else:
            data = get_today_history(lottery_code, date_from or None)
            draws = data.get("draws", [])
        writer.writerow(["期号", "开奖日期", "开奖号码", "试机号", "机球号", "投注总额", "奖池金额", "奖金详情"])
        for draw in draws:
            nums_str = _format_numbers_for_csv(draw.get("numbers", ""))
            trial = _safe_val(draw.get("trial_numbers", ""))
            machine = _safe_val(draw.get("machine_ball", ""))
            sale = _safe_val(draw.get("sale_amount", ""))
            pool = _safe_val(draw.get("prize_pool", ""))
            prizes = _format_prizes(draw.get("prizes", ""))
            writer.writerow([draw["draw_number"], draw["draw_date"], nums_str, trial, machine, sale, pool, prizes])

    else:
        return {"status": "error", "message": "不支持的导出类型"}

    csv_content = output.getvalue()
    output.close()

    filename = f"{lottery_code}_{export_type}_{datetime.now().strftime('%Y%m%d')}.csv"
    resp = PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
    # 设置每日下载标识Cookie（有效期到次日凌晨）
    import datetime as dt
    tomorrow = dt.datetime.now() + dt.timedelta(days=1)
    tomorrow_midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    max_age = int((tomorrow_midnight - dt.datetime.now()).total_seconds())
    resp.set_cookie(key="dl_limited", value="1", max_age=max_age, httponly=True)
    return resp


def _format_numbers_for_csv(nums):
    """将开奖号码格式化为CSV可读字符串"""
    if isinstance(nums, str):
        try: nums = json.loads(nums)
        except: return nums
    if isinstance(nums, list):
        return " ".join(str(n) for n in nums)
    elif isinstance(nums, dict):
        parts = []
        for key in ("red", "front", "main"):
            if key in nums:
                parts.append(" ".join(str(n) for n in nums[key]))
        for key in ("blue", "back", "special"):
            if key in nums:
                v = nums[key]
                if isinstance(v, list):
                    parts.append(" ".join(str(n) for n in v))
                else:
                    parts.append(str(v))
        return " | ".join(parts)
    return str(nums)


@router.get("/{lottery_code}/search-advanced")
async def api_search_advanced(
    lottery_code: str,
    draw_number: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    results, total = advanced_search_fn(
        lottery_code,
        draw_number=draw_number or None,
        date_from=date_from or None,
        date_to=date_to or None,
        page=page,
        limit=30,
    )
    return {"data": results, "total": total}


@router.get("/{lottery_code}/appear-detail")
async def api_appear_detail(lottery_code: str, q: str = ""):
    """获取某个号码的详细出现记录（已合并至 history-detail，保留向后兼容）"""
    if not q:
        return {"status": "error", "message": "请提供查询号码 q"}
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}
    periods, total = get_history_detail(lottery_code, q, "group", 1, 9999)
    return {"status": "success", "data": periods, "total": total}


# ============================================================
# 新增 API 端点
# ============================================================

@router.get("/types/{lottery_code}")
async def api_type_info(lottery_code: str):
    """获取单个彩种详细信息"""
    types = get_all_types()
    for t in types:
        if t["code"] == lottery_code:
            return {"status": "success", "data": t}
    return {"status": "error", "message": "彩票类型不存在"}


@router.get("/{lottery_code}/draw/{draw_number}")
async def api_draw_by_number(lottery_code: str, draw_number: str):
    """按期号查询单期开奖数据（支持短号模糊匹配，如 318 → 2025318）

    Args:
        lottery_code: 彩种代码
        draw_number: 期号（支持短号，自动匹配年份前缀）

    Returns:
        开奖记录含JSON解析后的字段
    """
    from app.database import match_draw_number
    from app.unused import get_draw_by_number

    # 先用 match_draw_number 做初步匹配（返回原始行）
    d = get_draw_by_number(lottery_code, draw_number)
    if not d:
        return {"status": "error", "message": "未找到该期号"}
    return {"status": "success", "data": d}


@router.get("/{lottery_code}/period-stats")
async def api_period_stats(lottery_code: str):
    """获取指定彩种各时间段的统计数据

    Returns:
        periods: [{key, label, count}, ...] 各时间段开奖期数
        first_date: 首期日期
        last_date: 末期日期
    """
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}
    from app.unused import get_period_stats_all
    data = get_period_stats_all(lottery_code)
    return {"status": "success", "data": data}


@router.get("/{lottery_code}/stats/grouped")
async def api_grouped_stats(lottery_code: str):
    """获取按出现次数分组的号码统计

    适用于大乐透、双色球、七星彩、快乐八等组合彩种。
    3D/排列三/排列五返回空。

    Returns:
        grouped_stats: bool
        groups: [{label, stats: [{count, numbers}, ...]}, ...]
        total_draws: int
    """
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}
    from app.stats_builder import get_grouped_stats
    data = get_grouped_stats(lottery_code)
    if data is None:
        return {"status": "success", "data": None, "message": "该彩种不适用分组统计"}
    return {"status": "success", "data": data}


@router.get("/{lottery_code}/draws/period")
async def api_draws_period(
    lottery_code: str,
    period: str = "all",
    date_from: str = "",
    date_to: str = "",
    draw_from: str = "",
    draw_to: str = "",
    page: int = 1,
    page_size: int = 50,
):
    """获取指定时间段内的开奖数据

    Args:
        lottery_code: 彩种代码
        period: 时间段 (1w/1m/6m/1y/3y/10y/all)
        date_from/to: 自定义日期范围
        draw_from/to: 期号范围
        page: 页码
        page_size: 每页条数

    Returns:
        draws: [开奖记录...]
        total, page, page_size, total_pages
        period_key, period_label
        has_prev, has_next
    """
    from app.unused import get_period_draws
    data = get_period_draws(lottery_code, period_key=period,
                             date_from=date_from, date_to=date_to,
                             draw_from=draw_from, draw_to=draw_to,
                             page=page, page_size=page_size)
    return {"status": "success", "data": data}


@router.get("/{lottery_code}/schedule")
async def api_lottery_schedule(lottery_code: str):
    """获取指定彩种的开奖时间配置

    Returns:
        lottery_code: str
        draw_days: [0-6] 开奖日（0=周一）
        draw_time: "HH:MM" 开奖时间
        days_cn: ["周一", ...] 中文开奖日
        next_draw: 下场开奖时间 ISO 格式
        countdown_seconds: 倒计时秒数
    """
    from app.draw_schedule import SCHEDULE, get_next_draw, DAYS_CN

    sched = SCHEDULE.get(lottery_code)
    if not sched:
        return {"status": "error", "message": "该彩种无开奖时间配置"}

    next_draw = get_next_draw(lottery_code)
    countdown = None
    if next_draw:
        countdown = int((next_draw - datetime.now()).total_seconds())

    return {
        "status": "success",
        "data": {
            "lottery_code": lottery_code,
            "draw_days": sched["days"],
            "draw_time": sched["time"],
            "days_cn": [DAYS_CN[d] for d in sched["days"]],
            "next_draw": next_draw.isoformat() if next_draw else None,
            "countdown_seconds": max(0, countdown) if countdown is not None else None,
        }
    }


# ============================================================
# 统计数据
# ============================================================

@router.get("/stats/system")
@cached(ttl=CACHE_SYSTEM_STATS_TTL)
async def api_system_stats():
    """系统统计信息（缓存5分钟）"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM lottery_draws")
    total_draws = cursor.fetchone()["cnt"]

    cursor.execute("SELECT COUNT(*) as cnt FROM number_stats")
    total_stats = cursor.fetchone()["cnt"]

    cursor.execute("SELECT lottery_code, COUNT(*) as cnt FROM lottery_draws GROUP BY lottery_code ORDER BY cnt DESC")
    per_type = {r["lottery_code"]: r["cnt"] for r in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) as cnt FROM lottery_types WHERE active=1")
    type_count = cursor.fetchone()["cnt"]

    conn.close()

    return {
        "status": "success",
        "data": {
            "total_draws": total_draws,
            "total_stats_records": total_stats,
            "type_count": type_count,
            "draws_per_type": per_type,
        }
    }


@router.get("/system/status")
@cached(ttl=CACHE_SYSTEM_STATUS_TTL)
async def api_system_status():
    """系统日志页面状态总览（合并冷却+倒计时+轮训状态，减少前端请求）"""
    from app.draw_schedule import get_all_countdowns
    from datetime import date

    conn = get_connection()
    cursor = conn.cursor()

    # 冷却状态
    cooldown = get_manual_update_cooldown()

    # 轮训日志（最近20条）
    cursor.execute(
        "SELECT * FROM update_log ORDER BY update_time DESC LIMIT 20"
    )
    logs = [dict(r) for r in cursor.fetchall()]

    # 今日已更新的彩种（基于 update_log 的实际记录）
    today_str = date.today().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT DISTINCT lottery_code FROM update_log WHERE date(update_time)=? AND status IN ('success','catchup')",
        (today_str,)
    )
    today_updated = set(r["lottery_code"] for r in cursor.fetchall())

    conn.close()

    # 开奖倒计时
    countdown_data = get_all_countdowns()

    # 轮训活动状态检测（重新打开连接，因为 conn 已关闭）
    try:
        conn2 = get_connection()
        cursor2 = conn2.cursor()
        cursor2.execute(
            "SELECT MAX(update_time) as last_time, message FROM update_log WHERE date(update_time)=?",
            (today_str,)
        )
        last_poll = cursor2.fetchone()
        poll_active = False
        if last_poll and last_poll["last_time"]:
            try:
                # 1. 当前时间必须在活动窗口内
                now = datetime.now()
                in_window = POLL_START_HOUR <= now.hour < POLL_END_HOUR
                # 2. 最新日志不能是终止性消息
                last_msg = last_poll["message"] or ""
                is_terminated = any(kw in last_msg for kw in ["轮训结束", "跳过轮训", "非活动窗口"])
                # 3. 30分钟内有操作
                last_poll_time = datetime.fromisoformat(last_poll["last_time"])
                recent_activity = (now - last_poll_time).total_seconds() < 1800

                poll_active = in_window and not is_terminated and recent_activity
            except (ValueError, TypeError):
                poll_active = False
        conn2.close()
    except Exception:
        poll_active = False

    return {
        "status": "success",
        "data": {
            "cooldown": cooldown,
            "logs": logs,
            "countdown": countdown_data,
            "today_updated": list(today_updated),
            "polling_active": poll_active,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    }

@router.get("/{lottery_code}/stats")
@router.get("/{lottery_code}/stats/overview")
async def api_stats_overview(lottery_code: str):
    """获取号码统计概览（直选/组选总数、Top10等）"""
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) as cnt, SUM(appear_count) as total_appear FROM number_stats WHERE lottery_code=? AND stat_type='direct'",
        (lottery_code,)
    )
    direct_row = cursor.fetchone()

    cursor.execute(
        "SELECT COUNT(*) as cnt, SUM(appear_count) as total_appear FROM number_stats WHERE lottery_code=? AND stat_type='group'",
        (lottery_code,)
    )
    group_row = cursor.fetchone()

    cursor.execute(
        "SELECT number_text, appear_count FROM number_stats WHERE lottery_code=? AND stat_type='direct' ORDER BY appear_count DESC LIMIT 10",
        (lottery_code,)
    )
    top_direct = [{"number": r["number_text"], "count": r["appear_count"]} for r in cursor.fetchall()]

    cursor.execute(
        "SELECT number_text, appear_count FROM number_stats WHERE lottery_code=? AND stat_type='direct' ORDER BY appear_count ASC LIMIT 10",
        (lottery_code,)
    )
    bottom_direct = [{"number": r["number_text"], "count": r["appear_count"]} for r in cursor.fetchall()]

    conn.close()

    return {
        "status": "success",
        "data": {
            "lottery_code": lottery_code,
            "direct_count": direct_row["cnt"] or 0,
            "direct_total_appear": direct_row["total_appear"] or 0,
            "group_count": group_row["cnt"] or 0,
            "group_total_appear": group_row["total_appear"] or 0,
            "top_direct": top_direct,
            "bottom_direct": bottom_direct,
        }
    }


# ============================================================
# 手动更新（全局冷却：1 小时，后端强制校验）
# 必须在 /update/{lottery_code} 之前定义，避免路由冲突
# ============================================================

@router.get("/update/manual-cooldown")
async def api_manual_update_cooldown():
    """获取手动更新冷却剩余秒数"""
    return {
        "status": "success",
        "cooldown": get_manual_update_cooldown(),
    }


@router.post("/update/manual")
async def api_manual_update():
    """手动触发全量更新（全局冷却 1 小时，后端校验）"""
    # 后端强制冷却校验
    if not can_manual_update():
        remaining = get_manual_update_cooldown()
        return {
            "status": "cooldown",
            "cooldown": remaining,
            "message": f"冷却中，请等待 {remaining} 秒",
        }

    import time
    start = time.time()
    set_manual_update_timestamp()  # 立即锁定，防止并发

    # 执行更新（force=True 强制全量 TXT 逐行校验）
    json_result = do_json_update()
    catch_up_result = catch_up_missing(force=True)
    cache_clear()

    elapsed = round(time.time() - start, 2)
    total_added = json_result.get("total_added", 0) + catch_up_result.get("total_added", 0)

    return {
        "status": "success",
        "total_added": total_added,
        "cooldown": 3600,
        "message": f"更新完成，新增 {total_added} 条记录（耗时 {elapsed} 秒）",
    }


# ============================================================
# 更新操作
# ============================================================

@router.post("/update/{lottery_code}")
async def api_update(lottery_code: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM lottery_types WHERE code=?", (lottery_code,))
    lt = cursor.fetchone()
    if not lt:
        conn.close()
        return {"status": "error", "message": "彩票类型不存在"}

    url = lt["data_url"]
    lines = fetch_data(url)
    if not lines:
        conn.close()
        return {"status": "error", "message": "数据抓取失败"}

    cursor.execute(
        "SELECT MAX(draw_number) as max_no FROM lottery_draws WHERE lottery_code=?",
        (lottery_code,)
    )
    row = cursor.fetchone()
    max_existing = row["max_no"] if row and row["max_no"] else "0"

    added = 0
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        draw_number = fields[0]
        if draw_number <= max_existing:
            continue
        parsed = parse_line(lottery_code, fields)
        if not parsed:
            continue
        draw_date = fields[1]

        cursor.execute("""
            INSERT OR IGNORE INTO lottery_draws
            (lottery_code, draw_number, draw_date, numbers, trial_numbers, machine_ball, draw_order, sale_amount, prize_pool, prizes, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lottery_code,
            draw_number,
            draw_date,
            json.dumps(parsed.get("numbers", [])),
            json.dumps(parsed.get("trial_numbers")) if parsed.get("trial_numbers") else None,
            json.dumps(parsed.get("machine_ball")) if parsed.get("machine_ball") else None,
            json.dumps(parsed.get("draw_order")) if parsed.get("draw_order") else None,
            parsed.get("sale_amount", 0),
            parsed.get("prize_pool"),
            json.dumps(parsed.get("prizes", [])),
            json.dumps(parsed.get("extra")) if parsed.get("extra") else None,
        ))
        if cursor.rowcount > 0:
            added += 1

    cursor.execute("""
        INSERT INTO update_log (lottery_code, status, records_added, message, operator)
        VALUES (?, 'success', ?, ?, 'manual_api')
    """, (lottery_code, added, f"新增{added}条记录"))

    conn.commit()
    conn.close()

    # 失效缓存
    cache_delete("api_system_stats")
    cache_delete(f"api_number_stats:('{lottery_code}',)")

    return {"status": "success", "message": f"更新完成，新增 {added} 条记录", "added": added}


@router.post("/{lottery_code}/build-stats")
async def api_build_stats(lottery_code: str):
    types = get_all_types()
    if not any(t["code"] == lottery_code for t in types):
        return {"status": "error", "message": "彩票类型不存在"}
    result = build_number_stats(lottery_code)
    return {"status": "success", "message": f"统计完成，共 {result['direct_count']} 个直选号码", **result}


@router.post("/rebuild-all-stats")
async def api_rebuild_all_stats():
    """重建所有彩种的号码统计"""
    types = get_all_types()
    results = {}
    for t in types:
        code = t["code"]
        try:
            r = build_number_stats(code)
            results[code] = {"direct_count": r["direct_count"], "status": "ok"}
        except Exception as e:
            results[code] = {"error": str(e), "status": "error"}
    return {
        "status": "success",
        "message": f"已重建 {len(results)} 个彩种统计",
        "results": results
    }


@router.post("/update-json")
async def api_update_json():
    """手动触发JSON API增量更新"""
    import time
    start = time.time()
    from app.auto_updater import do_json_update
    result = do_json_update()
    elapsed = round(time.time() - start, 2)

    # 失效所有缓存
    cache_clear()

    return {
        "status": "success" if result["total_added"] >= 0 else "error",
        "message": f"更新完成，新增 {result['total_added']} 条记录（耗时 {elapsed} 秒）",
        "data": result,
    }


@router.post("/catch-up")
async def api_catch_up():
    """手动触发断服补数据"""
    import time
    start = time.time()
    result = catch_up_missing()
    elapsed = round(time.time() - start, 2)
    cache_clear()

    if result["total_added"] > 0:
        msg = f"补数据完成，新增 {result['total_added']} 条记录（耗时 {elapsed} 秒）"
    else:
        msg = f"数据已完整，无需补充（耗时 {elapsed} 秒）"

    return {
        "status": "success",
        "message": msg,
        "data": result,
    }


# ============================================================
# 倒计时
# ============================================================

@router.get("/countdown")
@cached(ttl=CACHE_COUNTDOWN_TTL)
async def api_countdown():
    """获取所有彩种开奖倒计时（缓存30秒）"""
    from app.draw_schedule import get_all_countdowns
    return {"status": "success", "data": get_all_countdowns()}


# ============================================================
# 号码排行分析 API
# ============================================================

@router.get("/{lottery_code}/ranking/double")
async def api_double_digit_ranking(
    lottery_code: str,
    mode: str = "any",
    position: str = "0,1",
    page: int = 1,
    page_size: int = 50,
    date_from: str = "",
    date_to: str = "",
):
    """双号组合排行"""
    from app.analysis_service import get_double_digit_ranking

    position_pair = None
    if mode == "position" and position:
        parts = position.split(",")
        if len(parts) == 2:
            position_pair = (int(parts[0]), int(parts[1]))

    df = date_from or None
    dt = date_to or None
    result = get_double_digit_ranking(lottery_code, mode, position_pair, page, page_size, df, dt)
    if result is None:
        return {"status": "error", "message": "该彩种不支持双号组合排行"}
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/triple")
async def api_triple_group_ranking(
    lottery_code: str, page: int = 1, page_size: int = 50,
    date_from: str = "", date_to: str = "",
):
    """三号组选排行"""
    from app.analysis_service import get_triple_group_ranking

    df = date_from or None
    dt = date_to or None
    result = get_triple_group_ranking(lottery_code, page, page_size, df, dt)
    if result is None:
        return {"status": "error", "message": "该彩种不支持三号组选排行"}
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/tail")
async def api_tail_ranking(
    lottery_code: str, page: int = 1, page_size: int = 50,
    date_from: str = "", date_to: str = "",
):
    """排列五尾号排行"""
    from app.analysis_service import get_p5_tail_ranking

    if lottery_code != "p5":
        return {"status": "error", "message": "仅排列五支持尾号排行"}
    df = date_from or None
    dt = date_to or None
    result = get_p5_tail_ranking(page, page_size, df, dt)
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/blue")
async def api_blue_ranking(
    lottery_code: str, page: int = 1, page_size: int = 50,
    date_from: str = "", date_to: str = "",
):
    """蓝球（后区）号码排行"""
    from app.analysis_service import get_blue_ranking

    df = date_from or None
    dt = date_to or None
    result = get_blue_ranking(lottery_code, page, page_size, df, dt)
    if result is None:
        return {"status": "error", "message": "该彩种不支持蓝号排行"}
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/red")
async def api_red_ranking(
    lottery_code: str, page: int = 1, page_size: int = 50,
    date_from: str = "", date_to: str = "",
):
    """红球（前区）号码排行"""
    from app.analysis_service import get_red_ranking

    df = date_from or None
    dt = date_to or None
    result = get_red_ranking(lottery_code, page, page_size, df, dt)
    if result is None:
        return {"status": "error", "message": "该彩种不支持红号排行"}
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/number")
async def api_number_ranking(
    lottery_code: str, page: int = 1, page_size: int = 50,
    date_from: str = "", date_to: str = "",
):
    """号码排行（快乐八）"""
    from app.analysis_service import get_kl8_number_ranking

    if lottery_code != "kl8":
        return {"status": "error", "message": "仅快乐八支持号码排行"}
    df = date_from or None
    dt = date_to or None
    result = get_kl8_number_ranking(page, page_size, df, dt)
    return {"status": "success", "data": result}


@router.get("/{lottery_code}/ranking/query")
async def api_ranking_query(
    lottery_code: str,
    ranking_type: str = "",
    query_value: str = "",
    mode: str = "any",
    position: str = "0,1",
    date_from: str = "",
    date_to: str = "",
):
    """自定义出现次数查询（支持逗号分隔多值）"""
    from app.analysis_service import query_number_count, RANKING_TYPES

    df = date_from or None
    dt = date_to or None

    # 如果没传 ranking_type 或为 custom，自动检测
    if not ranking_type or ranking_type == "custom":
        avail = RANKING_TYPES.get(lottery_code, [])
        if avail:
            ranking_type = avail[0][0]  # 默认第一个排行类型
        else:
            # 无排行类型的彩种，自动识别
            auto_map = {
                "ssq": "blue", "dlt": "blue", "kl8": "number",
                "qxc": "number", "7lc": "number",
            }
            ranking_type = auto_map.get(lottery_code, "number")

    # 增强分隔符处理：支持逗号、中文逗号、空格、顿号、分号、竖线等
    raw = query_value.strip()
    # 将所有常见分隔符统一替换为逗号
    import re
    raw = re.sub(r"[，、；;|\s]+", ",", raw)
    parts = [v.strip() for v in raw.split(",") if v.strip()]

    if len(parts) > 1:
        items = []
        total_draws = 0
        for p in parts:
            r = query_number_count(lottery_code, ranking_type, p, mode, position, df, dt)
            if r.get("item"):
                total_draws = r.get("total_draws", 0) or total_draws
                items.append(r["item"])
        return {
            "status": "success",
            "data": {
                "multi": True,
                "found": len(items) > 0,
                "items": items,
                "total_draws": total_draws,
            },
        }
    else:
        result = query_number_count(lottery_code, ranking_type, parts[0] if parts else query_value,
                                     mode, position, df, dt)
        return {"status": "success", "data": result}
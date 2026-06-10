"""页面路由 - 所有HTML页面渲染"""

import json
import os
import sys
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_connection, get_latest_draw, get_all_latest_draws
from app.stats_service import search_by_number, get_history_detail, advanced_search
from app.stats_builder import get_all_number_stats
from app.unused import get_unused_numbers
from app.query_parser import parse_query_for_template

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


def get_total_records():
    """获取数据库总记录数"""
    conn = get_connection()
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM lottery_draws")
    total = cursor.fetchone()["cnt"]
    conn.close()
    return total


def get_draws(lottery_code, limit=50, offset=0, start_date="", end_date=""):
    """获取某彩票的历史开奖数据"""
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

    cursor.execute(
        f"SELECT COUNT(*) as total FROM lottery_draws WHERE {where}",
        params,
    )
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
# Jinja2 渲染
# ============================================================
import jinja2
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    enable_async=False,
)


def render(template_name, **context):
    """渲染模板"""
    template = jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(html)


# ============================================================
# 首页
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    types = get_all_types()
    conn = get_connection()
    codes = [t["code"] for t in types]
    latest_draws_map = get_all_latest_draws(conn, codes)
    latest_draws = []
    for t in types:
        draw = latest_draws_map.get(t["code"])
        if draw:
            latest_draws.append({"type": t, "draw": parse_draw_json(draw)})
    conn.close()

    import json
    from app.draw_schedule import get_all_countdowns
    countdown_data = get_all_countdowns()
    countdown_json = json.dumps(countdown_data)

    return render("index.html",
        types=types,
        latest_draws=latest_draws,
        page_title="首页",
        sub_page="home",
        total_records=get_total_records(),
        countdown_json=countdown_json,
        icon="🎱",
    )


# ============================================================
# 系统日志
# ============================================================

@router.get("/system", response_class=HTMLResponse)
async def lottery_system(request: Request):
    return render("system.html",
        page_title="系统日志",
        sub_page="system",
        icon="📋",
    )


# ============================================================
# 开奖记录
# ============================================================

@router.get("/{lottery_code}", response_class=HTMLResponse)
async def lottery_detail(request: Request, lottery_code: str, page: int = 1, start_date: str = "", end_date: str = ""):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break

    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    limit = 50
    offset = (page - 1) * limit
    draws, total = get_draws(lottery_code, limit, offset, start_date, end_date)
    total_pages = (total + limit - 1) // limit

    conn = get_connection()
    latest = get_latest_draw(conn, lottery_code)
    conn.close()
    latest = parse_draw_json(latest)

    return render("lottery_detail.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        draws=draws,
        latest=latest,
        page=page,
        total_pages=total_pages,
        total=total,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 开奖记录",
        sub_page="draws",
        start_date=start_date,
        end_date=end_date,
    )


# ============================================================
# 号码搜索
# ============================================================

@router.get("/{lottery_code}/search", response_class=HTMLResponse)
async def lottery_search(
    request: Request,
    lottery_code: str,
    q: str = "",
    search_type: str = "group",
    page: int = 1,
):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    results = []
    total = 0
    count_info = {}

    if q:
        # 数字彩类型：连续数字串自动拆分为逗号分隔
        if lottery_code in ("3d", "p3", "p5", "qxc") and q and ',' not in q and q.isdigit():
            q = ','.join(list(q))
        results, total, count_info = search_by_number(lottery_code, q, search_type, page, 30)

    query_parts = parse_query_for_template(lottery_code, q)

    for row in results:
        for key in ["numbers", "trial_numbers", "machine_ball", "draw_order", "prizes", "extra"]:
            if row.get(key) and isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except (json.JSONDecodeError, TypeError):
                    pass

    return render("lottery_search.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        results=results,
        total=total,
        count_info=count_info,
        query=q,
        query_parts=query_parts,
        search_type=search_type,
        page=page,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 号码查询",
        sub_page="search",
    )


# ============================================================
# 高级搜索
# ============================================================

@router.get("/{lottery_code}/advanced", response_class=HTMLResponse)
async def lottery_advanced(
    request: Request,
    lottery_code: str,
    draw_number: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    results = []
    total = 0
    if draw_number or date_from or date_to:
        results, total = advanced_search(
            lottery_code,
            draw_number=draw_number or None,
            date_from=date_from or None,
            date_to=date_to or None,
            page=page,
            limit=30,
        )

    return render("lottery_advanced.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        results=results,
        total=total,
        draw_number=draw_number,
        date_from=date_from,
        date_to=date_to,
        page=page,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 高级搜索",
        sub_page="advanced",
    )


# ============================================================
# 未开奖号码与开奖数据可视化
# ============================================================

@router.get("/{lottery_code}/unused", response_class=HTMLResponse)
async def lottery_unused(request: Request, lottery_code: str,
                         page: int = 1, year_range: str = "all",
                         date_from: str = "", date_to: str = "",
                         period: str = "all", draw_from: str = "", draw_to: str = ""):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    # 仅 3D/排列三/排列五 支持未开奖号码
    if lottery_code not in ("3d", "p3", "p5"):
        return RedirectResponse(url=f"/{lottery_code}")

    from app.unused import get_unused_numbers, get_period_draws, get_period_stats_all

    # 将 UI 传入的 period 参数映射到 year_range（get_unused_numbers 实际使用）
    if period and period != "all" and year_range == "all":
        # period 的键值来自 PERIOD_LABELS: 1w/1m/6m/1y/3y/10y/all
        # 与 get_unused_numbers 的 delta_map 兼容
        year_range = period

    # 未开奖号码数据
    unused_data = get_unused_numbers(lottery_code, page=page, page_size=200,
                                     year_range=year_range, date_from=date_from, date_to=date_to)

    # 时段开奖数据
    period_data = get_period_draws(lottery_code, period_key=period,
                                    date_from=date_from, date_to=date_to,
                                    draw_from=draw_from, draw_to=draw_to,
                                    page=page, page_size=30)
    period_stats = get_period_stats_all(lottery_code)

    return render("lottery_unused.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        unused_data=unused_data,
        period_data=period_data,
        period_stats=period_stats,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 未开奖号码",
        sub_page="unused",
        year_range=year_range,
        date_from=date_from,
        date_to=date_to,
        period=period,
        draw_from=draw_from,
        draw_to=draw_to,
    )


# ============================================================
# 历史的今天
# ============================================================

@router.get("/{lottery_code}/today", response_class=HTMLResponse)
async def lottery_today(request: Request, lottery_code: str,
                         date: str = "", draw_number: str = ""):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    from app.unused import get_today_history, get_draw_by_number

    if draw_number:
        draw = get_draw_by_number(lottery_code, draw_number)
        if draw:
            # 按期号查询时，获取该期号所在日期的全体历史数据
            draw_date = draw["draw_date"]
            date_data = get_today_history(lottery_code, draw_date)
            today_data = {
                "draws": date_data.get("draws", [draw]),
                "current_date": draw_date,
                "current_date_label": draw_date,
                "prev_date": date_data.get("prev_date"),
                "next_date": date_data.get("next_date"),
                "prev_draw": draw.get("prev_draw"),
                "next_draw": draw.get("next_draw"),
                "total": date_data.get("total", 1),
            }
        else:
            today_data = {
                "draws": [],
                "current_date": "",
                "current_date_label": "未找到",
                "prev_date": None,
                "next_date": None,
                "prev_draw": None,
                "next_draw": None,
                "total": 0,
            }
    else:
        today_data = get_today_history(lottery_code, date or None)

    return render("lottery_today.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        today_data=today_data,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 历史的今天",
        sub_page="today",
        date_param=date,
        draw_number_param=draw_number,
    )


# ============================================================
# 历史开出统计
# ============================================================

@router.get("/{lottery_code}/stats", response_class=HTMLResponse)
async def lottery_stats(request: Request, lottery_code: str, page: int = 1):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    # 分组统计彩种（组合几乎不重复，统计组合次数无意义）
    grouped_types = {"ssq", "dlt", "qxc", "kl8", "7lc"}
    if lottery_code in grouped_types:
        from app.stats_builder import get_grouped_stats
        stats_data = get_grouped_stats(lottery_code)
    else:
        stats_data = get_all_number_stats(lottery_code, page=page, page_size=100)

    return render("lottery_stats.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        stats_data=stats_data,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - 历史开出统计",
        sub_page="stats",
    )


# ============================================================
# 排行分析页面
# ============================================================

@router.get("/{lottery_code}/ranking", response_class=HTMLResponse)
@router.get("/{lottery_code}/ranking/{ranking_type}", response_class=HTMLResponse)
async def lottery_ranking(
    request: Request,
    lottery_code: str,
    ranking_type: str = "",
    mode: str = "any",
    position: str = "0,1",
    page: int = 1,
    date_from: str = "",
    date_to: str = "",
    date_range: str = "all",
):
    types = get_all_types()
    current_type = None
    for t in types:
        if t["code"] == lottery_code:
            current_type = t
            break
    if not current_type:
        return HTMLResponse("彩票类型不存在", status_code=404)

    from app.analysis_service import RANKING_TYPES, query_number_count

    available = RANKING_TYPES.get(lottery_code, [])
    # 无排行功能彩种：仍然渲染页面，展示自定义查询功能
    if not available:
        ranking_type = ""
        ranking_name = ""

    # 验证排行类型是否有效
    elif ranking_type and ranking_type not in [item[0] for item in available]:
        ranking_type = available[0][0]

    # 如果是有效的排行类型但未指定，默认第一个
    elif available and not ranking_type:
        ranking_type = available[0][0]

    # 获取排行类型名称
    ranking_name = ""
    for rtype, rname, _ in available:
        if rtype == ranking_type:
            ranking_name = rname
            break

    # 标题名称映射
    type_labels = {
        "3d": "3D", "p3": "排列三", "p5": "排列五",
        "ssq": "双色球", "dlt": "大乐透", "kl8": "快乐八",
    }
    lottery_label = type_labels.get(lottery_code, lottery_code)

    # 当前日期（用于 date input 的 max 属性）
    from datetime import date
    today = date.today().isoformat()

    return render("lottery_ranking.html",
        types=types,
        current_type=current_type,
        lottery_code=lottery_code,
        lottery_name=current_type["name"],
        lottery_label=lottery_label,
        ranking_type=ranking_type,
        ranking_name=ranking_name,
        available_rankings=available,
        mode=mode,
        position=position,
        page=page,
        total_records=get_total_records(),
        page_title=current_type["name"] + " - " + ranking_name,
        sub_page="ranking",
        date_from=date_from,
        date_to=date_to,
        date_range=date_range,
        today=today,
    )
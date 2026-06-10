"""未开奖号码分析模块"""

import json
from datetime import datetime, timedelta
from app.database import get_connection
from app.matcher import extract_number_string


def get_unused_numbers(lottery_code, page=1, page_size=200, year_range="all",
                       date_from="", date_to=""):
    """获取从未开出的号码列表（带分页和时间范围）

    支持自定义日期范围：若 date_from 和 date_to 同时提供，优先使用自定义日期

    ★ 始终从 lottery_draws 直接查询（来源表），避免 number_stats 不完整导致已开出号码被误列为未开出

    Args:
        lottery_code: 彩种代码
        page: 页码
        page_size: 每页数量
        year_range: 预设时间范围 (all/5y/3y/2y/1y/6m/3m/1m)
        date_from: 自定义起始日期 (YYYY-MM-DD)
        date_to: 自定义结束日期 (YYYY-MM-DD)

    Returns:
        dict 或 None（不支持该彩种时）
    """
    conn = get_connection()
    cursor = conn.cursor()

    if lottery_code in ("3d", "p3"):
        digits = 3
    elif lottery_code == "p5":
        digits = 5
    else:
        conn.close()
        return None

    today = datetime.now()
    range_label = _get_range_label(year_range, date_from, date_to)

    total_possible = 10 ** digits

    # ── 从 lottery_draws 中获取所有已开奖号码（源表，始终最新） ──
    conditions = ["lottery_code=?"]
    params = [lottery_code]

    # 优先使用自定义日期
    if date_from and date_to:
        conditions.append("draw_date >= ?")
        params.append(date_from)
        conditions.append("draw_date <= ?")
        params.append(date_to)
    else:
        # 预设时间范围
        delta_map = {
            "5y": 365 * 5,
            "3y": 365 * 3,
            "2y": 730,
            "1y": 365,
            "6m": 180,
            "3m": 90,
            "1m": 30,
            "1w": 7,
            "10y": 365 * 10,
        }
        days = delta_map.get(year_range)
        if days is not None:
            date_threshold = (today - timedelta(days=days)).strftime("%Y-%m-%d")
            conditions.append("draw_date >= ?")
            params.append(date_threshold)

    where = " AND ".join(conditions)

    cursor.execute(
        f"SELECT numbers FROM lottery_draws WHERE {where} ORDER BY draw_number",
        params
    )
    appeared = set()
    for row in cursor.fetchall():
        nums = json.loads(row["numbers"])
        num_str = extract_number_string(lottery_code, nums)
        if num_str:
            appeared.add(num_str)

    # ── 计算未开出的号码 ──
    unused = []
    for i in range(total_possible):
        num_str = str(i).zfill(digits)
        if num_str not in appeared:
            unused.append(num_str)

    unused_count = len(unused)
    appeared_count = len(appeared)
    total_pages = max(1, (unused_count + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    end = start + page_size
    page_data = unused[start:end]

    conn.close()

    coverage = round(appeared_count / total_possible * 100, 1) if total_possible > 0 else 0

    return {
        "stats": {
            "total_combs": total_possible,
            "opened_combs": appeared_count,
            "unused_combs": unused_count,
            "coverage": coverage,
        },
        "data": page_data,
        "total_pages": total_pages,
        "current_page": page,
        "page_size": page_size,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "year_range": year_range,
        "year_range_label": range_label,
        "date_from": date_from,
        "date_to": date_to,
    }


def _get_range_label(year_range, date_from, date_to):
    """获取日期范围显示标签"""
    if date_from and date_to:
        return f"{date_from} ~ {date_to}"
    labels = {
        "all": "全部历史", "5y": "近5年", "3y": "近3年",
        "2y": "近2年", "1y": "近1年",
        "6m": "近半年", "3m": "近3月", "1m": "近1月",
        "1w": "一周历史", "10y": "十年历史",
    }
    return labels.get(year_range, year_range or "全部历史")


# ============================================================
# 号码历史查询（未开奖号码页面使用）
# ============================================================

# 预设时间段（天）
TIME_PERIODS = [
    ("1w", "一周历史", 7),
    ("1m", "一月历史", 30),
    ("6m", "半年历史", 180),
    ("1y", "一年历史", 365),
    ("3y", "三年历史", 365 * 3),
    ("10y", "十年历史", 365 * 10),
    ("all", "全部历史", None),
]

# 时段开奖数据查询共享常量
PERIOD_LABELS = TIME_PERIODS  # 复用 TIME_PERIODS


def check_number_history(lottery_code, number_str, num_type="single"):
    """查询指定号码在各历史时间段是否开出及出现次数

    Args:
        lottery_code: 彩种代码
        number_str: 号码字符串（如 "07" 或 "07,12"）
        num_type: 号码类型（"single"=单号码, "red"=红号, "blue"=蓝号）

    Returns:
        dict: {periods: [{key, label, appeared, count}], total_draws: int}
    """
    from datetime import datetime, timedelta
    import json

    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now()

    # 获取所有开奖数据
    cursor.execute(
        "SELECT draw_date, numbers FROM lottery_draws WHERE lottery_code=? ORDER BY draw_date ASC",
        (lottery_code,)
    )
    rows = cursor.fetchall()
    conn.close()

    # 解析查询号码
    try:
        query_num = int(number_str.strip())
    except ValueError:
        return {"periods": [], "total_draws": 0}

    total_draws = len(rows)
    periods = []

    for key, label, days in TIME_PERIODS:
        # 计算日期阈值
        if days is None:
            threshold = None  # 全部历史
        else:
            threshold = (today - timedelta(days=days)).strftime("%Y-%m-%d")

        count = 0
        appeared = False

        for row in rows:
            draw_date = row["draw_date"]

            # 时间范围过滤
            if threshold and draw_date < threshold:
                continue

            try:
                nums = json.loads(row["numbers"])
            except (json.JSONDecodeError, TypeError):
                continue

            # 根据彩种和号码类型匹配
            found = _check_number_in_draw(nums, lottery_code, query_num, num_type)
            if found:
                count += 1
                appeared = True

        periods.append({
            "key": key,
            "label": label,
            "appeared": appeared,
            "count": count,
        })

    return {"periods": periods, "total_draws": total_draws}


def _check_number_in_draw(nums, lottery_code, query_num, num_type):
    """检查号码是否在开奖号码中"""
    if isinstance(nums, list):
        # 个位数彩种（3D/P3/P5/QXC）：号码为多位数字的各位，需拼接后比较
        if lottery_code in ("3d", "p3", "p5", "qxc"):
            num_str = "".join(str(n) for n in nums)
            query_str = str(query_num).zfill(len(nums))
            return num_str == query_str
        # 简单列表（KL8等）：直接查询单个数字是否存在
        return query_num in nums

    elif isinstance(nums, dict):
        if num_type == "red" or num_type == "single":
            # 红球/前区/基本号
            for key in ("red", "front", "main"):
                if key in nums and query_num in nums[key]:
                    return True
        if num_type == "blue" or num_type == "single":
            # 蓝球/后区
            if "blue" in nums and nums["blue"] == query_num:
                return True
            if "back" in nums and query_num in nums["back"]:
                return True
            if "special" in nums and nums["special"] == query_num:
                return True
        # 所有号码中查找
        if num_type == "single":
            for key in nums:
                val = nums[key]
                if isinstance(val, list) and query_num in val:
                    return True
                elif isinstance(val, int) and val == query_num:
                    return True

    return False


# ============================================================
# 时段开奖数据查询（未开奖号页面可视化表格）
# ============================================================

# 预设时间段标签
PERIOD_LABELS = TIME_PERIODS  # 复用 TIME_PERIODS


def get_period_draws(lottery_code, period_key="all",
                     date_from="", date_to="",
                     draw_from="", draw_to="",
                     page=1, page_size=50):
    """获取指定彩种在某时间段的开奖数据

    Args:
        lottery_code: 彩种代码
        period_key: 时间段 (1w/1m/6m/1y/3y/10y/all)
        date_from/to: 自定义日期范围筛选
        draw_from/to: 期号范围筛选
        page: 页码
        page_size: 每页条数

    Returns:
        dict: {draws: [...], total, page, page_size, total_pages,
               period_key, period_label, count_by_period: {...}}
    """
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now()

    # 计算时间段日期阈值
    period_days = None
    period_label = "全部历史"
    for key, label, days in PERIOD_LABELS:
        if key == period_key:
            period_days = days
            period_label = label
            break

    # 构建 WHERE 条件
    conditions = ["lottery_code=?"]
    params = [lottery_code]

    # 时间段日期过滤
    if period_days is not None:
        threshold = (today - timedelta(days=period_days)).strftime("%Y-%m-%d")
        conditions.append("draw_date >= ?")
        params.append(threshold)

    # 自定义日期范围（覆盖时间段）
    if date_from:
        conditions.append("draw_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("draw_date <= ?")
        params.append(date_to)

    # 期号范围
    if draw_from:
        conditions.append("draw_number >= ?")
        params.append(draw_from)
    if draw_to:
        conditions.append("draw_number <= ?")
        params.append(draw_to)

    where = " AND ".join(conditions)

    # 查询总数
    cursor.execute(f"SELECT COUNT(*) as cnt FROM lottery_draws WHERE {where}", params)
    total = cursor.fetchone()["cnt"]

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    # 查询数据
    cursor.execute(
        f"SELECT * FROM lottery_draws WHERE {where} ORDER BY draw_number DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    rows = cursor.fetchall()
    draws = []
    for row in rows:
        d = dict(row)
        for key in ("numbers", "prizes", "trial_numbers", "machine_ball", "draw_order"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        draws.append(d)

    conn.close()

    return {
        "draws": draws,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "period_key": period_key,
        "period_label": period_label,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def get_period_stats_all(lottery_code):
    """获取所有时间段的统计数据（单次查询优化）"""
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now()

    # 单次查询获取所有时间段计数
    stats = []
    for key, label, days in PERIOD_LABELS:
        if days is None:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM lottery_draws WHERE lottery_code=?",
                (lottery_code,)
            )
        else:
            threshold = (today - timedelta(days=days)).strftime("%Y-%m-%d")
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM lottery_draws WHERE lottery_code=? AND draw_date >= ?",
                (lottery_code, threshold)
            )
        count = cursor.fetchone()["cnt"]
        stats.append({"key": key, "label": label, "count": count})

    # 总期数 + 首末日期（单次查询）
    cursor.execute(
        "SELECT MIN(draw_date) as first, MAX(draw_date) as last FROM lottery_draws WHERE lottery_code=?",
        (lottery_code,)
    )
    row = cursor.fetchone()
    conn.close()

    return {
        "periods": stats,
        "first_date": row["first"] if row else "",
        "last_date": row["last"] if row else "",
    }


def get_unused_for_qxc(lottery_code, date_from="", date_to=""):
    """获取七星彩的未开奖号码（基于date范围）

    七星彩是7位数字，理论上从0000000到9999999共1千万个号码。
    基于已开奖号码取反即可，但1千万太多无法全部显示。
    这里只返回统计信息。
    """
    if lottery_code != "qxc":
        return None

    conn = get_connection()
    cursor = conn.cursor()

    # 已开出的号码
    cursor.execute(
        "SELECT number_text FROM number_stats WHERE lottery_code=? AND stat_type='direct'",
        (lottery_code,)
    )
    appeared = set(row["number_text"] for row in cursor.fetchall())
    conn.close()

    total_possible = 10 ** 7
    appeared_count = len(appeared)
    unused_count = total_possible - appeared_count
    coverage = round(appeared_count / total_possible * 100, 4) if total_possible > 0 else 0

    return {
        "total_combs": total_possible,
        "opened_combs": appeared_count,
        "unused_combs": unused_count,
        "coverage": coverage,
    }


# ============================================================
# 历史的今天
# ============================================================

def get_today_history(lottery_code, date_str=None):
    """获取某彩票类型在指定日期（月-日）的所有历史开奖

    Args:
        lottery_code: 彩种代码
        date_str: 日期字符串 YYYY-MM-DD，为 None 时使用今天

    Returns:
        dict: {
            draws: [{draw_number, draw_date, numbers, ...}],
            current_date: str, (YYYY-MM-DD)
            prev_date: str,
            next_date: str,
            prev_draw: str or None,
            next_draw: str or None,
            total: int
        }
    """
    from datetime import datetime, timedelta
    import json

    conn = get_connection()
    cursor = conn.cursor()

    today = datetime.now()
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            target = today
    else:
        target = today

    # 查找月-日相同的所有记录
    month_day = target.strftime("%m-%d")
    cursor.execute(
        "SELECT * FROM lottery_draws WHERE lottery_code=? AND strftime('%m-%d', draw_date)=? ORDER BY draw_number DESC",
        (lottery_code, month_day)
    )
    rows = cursor.fetchall()
    draws = []
    for row in rows:
        d = dict(row)
        for key in ("numbers", "prizes", "trial_numbers", "machine_ball", "draw_order"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        draws.append(d)

    # 相邻日期（始终 +/- 1 天，不跳过无数据日期）
    one_day = timedelta(days=1)
    prev_date = (target - one_day).strftime("%Y-%m-%d")
    next_date = (target + one_day).strftime("%Y-%m-%d")

    # 上一期/下一期（在全部历史中找，不局限于当前日期）
    current_draw = draws[0]["draw_number"] if draws else None
    prev_draw = None
    next_draw = None
    if current_draw:
        # 上一期
        cursor.execute(
            "SELECT draw_number FROM lottery_draws WHERE lottery_code=? AND draw_number < ? ORDER BY draw_number DESC LIMIT 1",
            (lottery_code, current_draw)
        )
        row = cursor.fetchone()
        if row:
            prev_draw = row["draw_number"]
        # 下一期
        cursor.execute(
            "SELECT draw_number FROM lottery_draws WHERE lottery_code=? AND draw_number > ? ORDER BY draw_number ASC LIMIT 1",
            (lottery_code, current_draw)
        )
        row = cursor.fetchone()
        if row:
            next_draw = row["draw_number"]

    conn.close()

    return {
        "draws": draws,
        "current_date": target.strftime("%Y-%m-%d"),
        "current_date_label": target.strftime("%Y-%m-%d"),
        "prev_date": prev_date,
        "next_date": next_date,
        "prev_draw": prev_draw,
        "next_draw": next_draw,
        "total": len(draws),
    }


def get_draw_by_number(lottery_code, draw_number):
    """按期号查询开奖数据，附带前后期号

    支持忽略日期前缀的模糊匹配（如输入 '318' 可匹配 '2025318'）

    Args:
        lottery_code: 彩种代码
        draw_number: 期号（支持短号，如 "318"）

    Returns:
        dict | None: 开奖记录（含 prev_draw、next_draw），或 None
    """
    import json
    from app.database import match_draw_number

    d = match_draw_number(lottery_code, draw_number)
    if not d:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    # 解析JSON字段
    for key in ("numbers", "prizes", "trial_numbers", "machine_ball", "draw_order"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass

    # 查找前后期号
    prev_draw = None
    next_draw = None
    cursor.execute(
        "SELECT draw_number FROM lottery_draws WHERE lottery_code=? AND draw_number < ? ORDER BY draw_number DESC LIMIT 1",
        (lottery_code, d["draw_number"])
    )
    row = cursor.fetchone()
    if row:
        prev_draw = row["draw_number"]

    cursor.execute(
        "SELECT draw_number FROM lottery_draws WHERE lottery_code=? AND draw_number > ? ORDER BY draw_number ASC LIMIT 1",
        (lottery_code, d["draw_number"])
    )
    row = cursor.fetchone()
    if row:
        next_draw = row["draw_number"]

    conn.close()
    d["prev_draw"] = prev_draw
    d["next_draw"] = next_draw
    return d
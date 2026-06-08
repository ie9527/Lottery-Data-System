"""统计服务层 - 号码搜索、历史详情、高级搜索"""

import json
from app.database import get_connection
from app.query_parser import parse_search_query
from app.matcher import (
    SINGLE_DIGIT_TYPES, extract_number_string, extract_sorted_string,
    wildcard_match, prefix_match, match_list, numbers_contains,
    set_subset_match_mode, match_dict
)


def _compute_is_direct(lottery_code, nums, query_obj, search_type):
    """计算单行结果是否为直选匹配（供 search_by_number 和 get_history_detail 共用）"""
    if lottery_code in SINGLE_DIGIT_TYPES and query_obj and query_obj["type"] == "list":
        q_nums_raw = query_obj["numbers"]
        q_nums = [n for n in q_nums_raw if n is not None]
        draw_nums = nums
        return (len(q_nums) == len(draw_nums) and q_nums == draw_nums)
    elif query_obj and query_obj.get("match_mode") == "subset":
        # 子集匹配时，显示标签跟随用户选择的搜索模式
        return (search_type == "direct")
    else:
        return (search_type == "direct")


def search_by_number(lottery_code, search_text, search_type="direct", page=1, limit=50):
    """按号码查询历史开奖记录（优化版 - 两阶段加载）

    Returns:
        (结果列表, 总条数, 出现次数统计)
    """
    conn = get_connection()
    cursor = conn.cursor()

    offset = (page - 1) * limit
    results = []
    total = 0
    count_info = {}

    query_obj = parse_search_query(lottery_code, search_text)

    # ─── 第一阶段：仅加载 id 和 numbers ───
    cursor.execute(
        "SELECT id, numbers FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC",
        (lottery_code,)
    )
    all_rows = cursor.fetchall()

    matched_ids = []
    for row in all_rows:
        try:
            nums = json.loads(row["numbers"])
        except (json.JSONDecodeError, TypeError):
            continue

        matched = _match_row(lottery_code, nums, query_obj, search_text, search_type)

        if matched:
            matched_ids.append(row["id"])

    total = len(matched_ids)

    if not matched_ids:
        conn.close()
        return [], 0, count_info

    # ─── 第二阶段：精确加载匹配行的完整数据 ───
    page_ids = matched_ids[offset:offset + limit]
    if not page_ids:
        conn.close()
        return [], total, count_info

    placeholders = ",".join("?" * len(page_ids))
    cursor.execute(
        f"SELECT * FROM lottery_draws WHERE id IN ({placeholders}) ORDER BY draw_number DESC",
        page_ids
    )
    results = [dict(row) for row in cursor.fetchall()]

    # 补充 is_direct 字段
    for row in results:
        try:
            nums = json.loads(row["numbers"])
        except (json.JSONDecodeError, TypeError):
            nums = row.get("numbers")
        row["is_direct"] = _compute_is_direct(lottery_code, nums, query_obj, search_type)

    # ─── 获取统计信息 ───
    if query_obj and query_obj["type"] == "list":
        q_nums = [n for n in query_obj["numbers"] if n is not None]
        if q_nums:
            sorted_q = sorted(q_nums)
            if lottery_code in SINGLE_DIGIT_TYPES:
                q_str_direct = "".join(str(n) for n in q_nums)
                q_str_group = "".join(str(n) for n in sorted_q)
            else:
                q_str_direct = "".join(str(n).zfill(2) for n in q_nums)
                q_str_group = "".join(str(n).zfill(2) for n in sorted_q)

            cursor.execute(
                "SELECT appear_count FROM number_stats WHERE lottery_code=? AND number_text=? AND stat_type='direct'",
                (lottery_code, q_str_direct)
            )
            row = cursor.fetchone()
            count_info["direct_count"] = row["appear_count"] if row else 0

            cursor.execute(
                "SELECT appear_count FROM number_stats WHERE lottery_code=? AND number_text=? AND stat_type='group'",
                (lottery_code, q_str_group)
            )
            row = cursor.fetchone()
            count_info["group_count"] = row["appear_count"] if row else 0

    conn.close()
    return results, total, count_info


def get_history_detail(lottery_code, search_text, search_type, page=1, limit=50):
    """获取历史开出的具体期数详情"""
    conn = get_connection()
    cursor = conn.cursor()

    offset = (page - 1) * limit
    query_obj = parse_search_query(lottery_code, search_text)

    cursor.execute(
        "SELECT id, numbers FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC",
        (lottery_code,)
    )
    all_rows = cursor.fetchall()

    matched_ids = []
    for row in all_rows:
        try:
            nums = json.loads(row["numbers"])
        except (json.JSONDecodeError, TypeError):
            continue
        matched = _match_row(lottery_code, nums, query_obj, search_text, search_type)
        if matched:
            matched_ids.append(row["id"])

    total = len(matched_ids)

    if not matched_ids:
        conn.close()
        return [], 0

    page_ids = matched_ids[offset:offset + limit]
    if not page_ids:
        conn.close()
        return [], total

    placeholders = ",".join("?" * len(page_ids))
    cursor.execute(
        f"SELECT id, draw_number, draw_date, numbers FROM lottery_draws WHERE id IN ({placeholders}) ORDER BY draw_number DESC",
        page_ids
    )
    rows = cursor.fetchall()

    periods = []
    for row in rows:
        entry = {
            "draw_number": row["draw_number"],
            "draw_date": row["draw_date"],
            "numbers": json.loads(row["numbers"])
        }
        entry["is_direct"] = _compute_is_direct(lottery_code, entry["numbers"], query_obj, search_type)
        periods.append(entry)

    conn.close()
    return periods, total


def advanced_search(lottery_code, draw_number=None, date_from=None, date_to=None, page=1, limit=50):
    """高级搜索：按期号、日期范围搜索"""
    conn = get_connection()
    cursor = conn.cursor()

    conditions = ["lottery_code=?"]
    params = [lottery_code]

    if draw_number:
        conditions.append("draw_number LIKE ?")
        params.append(f"%{draw_number}%")

    if date_from:
        conditions.append("draw_date >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("draw_date <= ?")
        params.append(date_to)

    where = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) as cnt FROM lottery_draws WHERE {where}", params)
    total = cursor.fetchone()["cnt"]

    offset = (page - 1) * limit
    cursor.execute(
        f"SELECT * FROM lottery_draws WHERE {where} ORDER BY draw_number DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    )
    rows = [dict(row) for row in cursor.fetchall()]

    for row in rows:
        for key in ["numbers", "trial_numbers", "machine_ball", "draw_order", "prizes", "extra"]:
            if row.get(key):
                try:
                    row[key] = json.loads(row[key])
                except (json.JSONDecodeError, TypeError):
                    pass

    conn.close()
    return rows, total


def _match_row(lottery_code, nums, query_obj, search_text, search_type):
    """单行匹配逻辑（供内部复用）"""
    matched = False

    if query_obj is None:
        if search_type == "direct":
            num_str = extract_number_string(lottery_code, nums)
            matched = (search_text in num_str)
        else:
            group_str = extract_sorted_string(lottery_code, nums)
            matched = (search_text in group_str)

    elif lottery_code == "kl8":
        if query_obj["type"] == "list":
            matched = numbers_contains(nums, query_obj["numbers"])

    elif lottery_code in ("3d", "p3", "p5", "qxc"):
        if query_obj["type"] == "list":
            q_nums = query_obj["numbers"]
            has_wild = query_obj.get("has_wildcard", False)
            standard_len = {"3d": 3, "p3": 3, "p5": 5, "qxc": 7}.get(lottery_code, 3)

            if search_type == "direct":
                if has_wild:
                    if len(q_nums) == standard_len:
                        matched = wildcard_match(nums, q_nums)
                    else:
                        matched = wildcard_match(nums[:len(q_nums)], q_nums)
                elif len(q_nums) < standard_len:
                    matched = prefix_match(nums, q_nums)
                else:
                    matched = match_list(nums, q_nums, "direct")
            else:
                q_filtered = [n for n in q_nums if n is not None]
                if not q_filtered:
                    matched = False
                elif has_wild:
                    from collections import Counter
                    qc = Counter(q_filtered)
                    dc = Counter(nums)
                    matched = all(dc[k] >= v for k, v in qc.items())
                else:
                    matched = (sorted(q_filtered) == sorted(nums))

    elif lottery_code in ("ssq", "dlt", "7lc"):
        if query_obj and query_obj["type"] in ("red_blue", "front_back", "main_special"):
            set_subset_match_mode(query_obj, lottery_code)
        matched = match_dict(nums, query_obj, search_type)

        # 全部分类搜索：检查查询号码是否包含在开奖号码的任意位置
        if not matched and query_obj and query_obj.get("type") == "all":
            all_draw_nums = []
            if isinstance(nums, dict):
                for key in ("red", "front", "main", "blue", "back", "special"):
                    vals = nums.get(key)
                    if isinstance(vals, list):
                        all_draw_nums.extend(vals)
                    elif vals is not None:
                        all_draw_nums.append(vals)
            q_nums = query_obj.get("numbers", [])
            if search_type == "direct":
                matched = sorted(all_draw_nums) == sorted(q_nums)
            else:
                # 组选模式：查询号码是开奖号码的子集
                from collections import Counter
                dc = Counter(all_draw_nums)
                qc = Counter(q_nums)
                matched = all(dc[k] >= v for k, v in qc.items())

    return matched
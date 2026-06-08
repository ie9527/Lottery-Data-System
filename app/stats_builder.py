"""统计构建模块 - 构建和检索号码频率统计"""

import json
from collections import Counter
from app.database import get_connection
from app.matcher import SINGLE_DIGIT_TYPES, extract_number_string, extract_sorted_string


def build_number_stats(lottery_code):
    """构建某彩票的号码统计信息（全量重建）"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM number_stats WHERE lottery_code=?", (lottery_code,))
    cursor.execute(
        "SELECT numbers FROM lottery_draws WHERE lottery_code=?",
        (lottery_code,)
    )
    rows = cursor.fetchall()

    direct_stats = {}
    group_stats = {}

    for row in rows:
        nums = json.loads(row["numbers"])
        direct_str = extract_number_string(lottery_code, nums)
        group_str = extract_sorted_string(lottery_code, nums)

        if direct_str:
            direct_stats[direct_str] = direct_stats.get(direct_str, 0) + 1
        if group_str:
            group_stats[group_str] = group_stats.get(group_str, 0) + 1

    for num_str, count in direct_stats.items():
        cursor.execute(
            "INSERT OR REPLACE INTO number_stats (lottery_code, number_text, stat_type, appear_count) VALUES (?, ?, 'direct', ?)",
            (lottery_code, num_str, count)
        )
    for num_str, count in group_stats.items():
        cursor.execute(
            "INSERT OR REPLACE INTO number_stats (lottery_code, number_text, stat_type, appear_count) VALUES (?, ?, 'group', ?)",
            (lottery_code, num_str, count)
        )
    conn.commit()

    total = len(direct_stats)
    conn.close()
    return {"direct_count": len(direct_stats), "group_count": len(group_stats), "total": total}


def get_all_number_stats(lottery_code, page=1, page_size=100):
    """获取历史开出次数统计（按号码排序，分页）

    ★ 修复：组选 key 是排序后的数字字符串（如 085 → 058），
      不能直接用 number_text join，需用 Python 映射查找。
    """
    conn = get_connection()
    cursor = conn.cursor()

    offset = (page - 1) * page_size

    cursor.execute("""
        SELECT number_text, appear_count
        FROM number_stats
        WHERE lottery_code = ? AND stat_type = 'direct'
        ORDER BY CAST(number_text AS INTEGER) ASC
    """, (lottery_code,))
    direct_rows = cursor.fetchall()

    cursor.execute("""
        SELECT number_text, appear_count
        FROM number_stats
        WHERE lottery_code = ? AND stat_type = 'group'
    """, (lottery_code,))
    group_lookup = {row["number_text"]: row["appear_count"] for row in cursor.fetchall()}

    total = len(direct_rows)
    page_rows = direct_rows[offset:offset + page_size]

    items = []
    total_direct = 0
    total_group = 0
    for row in page_rows:
        direct_text = row["number_text"]
        if lottery_code in SINGLE_DIGIT_TYPES:
            sorted_digits = sorted(direct_text)
            group_key = "".join(sorted_digits)
        else:
            group_key = direct_text
        group_count = group_lookup.get(group_key, 0)

        items.append({
            "number": direct_text,
            "direct_count": row["appear_count"],
            "group_count": group_count
        })
        total_direct += row["appear_count"]
        total_group += group_count

    conn.close()

    total_pages = max(1, (total + page_size - 1) // page_size)

    return {
        "stats": items,
        "direct_total": total_direct,
        "group_total": total_group,
        "total_numbers": total,
        "current_page": page,
        "total_pages": total_pages
    }


# ============================================================
# 按出现次数分组统计（适用于 SSQ/DLT/QXC/KL8）
# ============================================================

def _build_ball_group(counter, label, full_range=None):
    """将单个号码出现次数的Counter按次数分组，并显示未出现号码"""
    count_groups = {}
    appeared = set()
    for num, cnt in counter.items():
        count_groups.setdefault(cnt, []).append(num)
        appeared.add(num)

    stats = []
    for cnt in sorted(count_groups.keys(), reverse=True):
        numbers = sorted(count_groups[cnt])
        stats.append({
            "count": cnt,
            "numbers": numbers,
        })

    # 计算未出现的号码
    not_appeared = []
    if full_range:
        for n in full_range:
            if n not in appeared:
                not_appeared.append(n)
    if not_appeared:
        stats.append({
            "count": 0,
            "numbers": sorted(not_appeared),
            "is_unappeared": True,
        })

    return {"label": label, "stats": stats}


def get_grouped_stats(lottery_code):
    """获取按出现次数分组的号码统计

    统计单个号码/数字的出现次数，然后按出现次数分组显示。
    适用于 SSQ/DLT/QXC/KL8（组合几乎不重复的彩种）。
    3D/P3/P5 仍使用原有的 get_all_number_stats。

    Returns:
        dict with "grouped_stats": True,
              "groups": [{"label": str, "stats": [{"count": int, "numbers": [int,...]}, ...]}, ...]
              "total_draws": int
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT numbers FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number ASC",
        (lottery_code,)
    )
    rows = cursor.fetchall()
    conn.close()

    total_draws = len(rows)
    groups = []

    if lottery_code == "ssq":
        # 红球（1-33）和蓝球（1-16）分别统计
        red_counter = Counter()
        blue_counter = Counter()
        for row in rows:
            nums = json.loads(row["numbers"])
            if not isinstance(nums, dict):
                continue
            red = nums.get("red", [])
            blue = nums.get("blue")
            if isinstance(red, list):
                for n in red:
                    red_counter[n] += 1
            if blue is not None:
                blue_counter[blue] += 1
        groups.append(_build_ball_group(red_counter, "红球（1-33）", full_range=list(range(1, 34))))
        groups.append(_build_ball_group(blue_counter, "蓝球（1-16）", full_range=list(range(1, 17))))

    elif lottery_code == "dlt":
        # 前区（1-35）和后区（1-12）分别统计
        front_counter = Counter()
        back_counter = Counter()
        for row in rows:
            nums = json.loads(row["numbers"])
            if not isinstance(nums, dict):
                continue
            front = nums.get("front", [])
            back = nums.get("back", [])
            if isinstance(front, list):
                for n in front:
                    front_counter[n] += 1
            if isinstance(back, list):
                for n in back:
                    back_counter[n] += 1
        groups.append(_build_ball_group(front_counter, "前区（1-35）", full_range=list(range(1, 36))))
        groups.append(_build_ball_group(back_counter, "后区（1-12）", full_range=list(range(1, 13))))

    elif lottery_code == "qxc":
        # 统计每个数字（0-9）在全部7位中的出现总次数
        digit_counter = Counter()
        for row in rows:
            nums = json.loads(row["numbers"])
            if not isinstance(nums, list):
                continue
            for n in nums:
                digit_counter[n] += 1
        groups.append(_build_ball_group(digit_counter, "数字（0-9）", full_range=list(range(0, 10))))

    elif lottery_code == "kl8":
        # 统计每个号码（1-80）的出现次数
        num_counter = Counter()
        for row in rows:
            nums = json.loads(row["numbers"])
            if not isinstance(nums, list):
                continue
            for n in nums:
                num_counter[n] += 1
        groups.append(_build_ball_group(num_counter, "号码（1-80）", full_range=list(range(1, 81))))

    else:
        # 其他彩种（3D/P3/P5）不适用，返回空
        return None

    return {
        "grouped_stats": True,
        "groups": groups,
        "total_draws": total_draws,
    }
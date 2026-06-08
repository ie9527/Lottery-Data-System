"""号码排行分析引擎 - 提供多种号码出现频率排行"""
import json
import logging
from collections import Counter
from app.database import get_connection

logger = logging.getLogger("lottery")


# ============================================================
# 公用：获取某彩种开奖号码（支持日期筛选）
# ============================================================
def _load_all_numbers(lottery_code, date_from=None, date_to=None):
    """加载某彩种开奖号码列表，支持日期范围筛选"""
    conn = get_connection()
    cursor = conn.cursor()

    sql = "SELECT numbers, draw_date FROM lottery_draws WHERE lottery_code=?"
    params = [lottery_code]
    if date_from:
        sql += " AND draw_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND draw_date <= ?"
        params.append(date_to)

    # 按期号升序，保证统计时排序一致
    sql += " ORDER BY draw_number ASC"

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"数据库查询失败 [{lottery_code}]: {e}")
        rows = []
    finally:
        conn.close()

    all_nums = []
    for row in rows:
        try:
            nums = json.loads(row["numbers"])
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"JSON解析失败 [{lottery_code}]: {row.get('numbers', '')} → {e}")
            continue
        all_nums.append(nums)
    logger.info(f"加载 [{lottery_code}] 数据: {len(all_nums)} 条 (date_from={date_from}, date_to={date_to})")
    return all_nums


def _calc_probability(count, total):
    """计算概率（百分比）"""
    if total == 0:
        return 0
    return round(count / total * 100, 2)


def _build_paginated_result(counter, total_draws, page, page_size, extra=None):
    """构建分页和排行结果"""
    try:
        sorted_items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    except Exception as e:
        logger.error(f"_build_paginated_result 排序失败: {e}", exc_info=True)
        sorted_items = []
    total_combos = len(sorted_items)
    offset = (page - 1) * page_size
    page_items = sorted_items[offset:offset + page_size]
    total_pages = max(1, (total_combos + page_size - 1) // page_size)

    result = {
        "items": [],
        "total": total_combos,
        "total_draws": total_draws,
        "current_page": page,
        "total_pages": total_pages,
    }
    if extra:
        result.update(extra)

    rank = offset + 1
    for key, count in page_items:
        try:
            # 兼容不同类型的 key：int → {"number": key}, tuple/dict → 直接展开
            if isinstance(key, dict):
                item = {"rank": rank, **key}
            elif isinstance(key, (int, str)):
                item = {"rank": rank, "number": key}
            elif isinstance(key, tuple):
                # 元组尝试作为组合号码展开
                item = {"rank": rank, "combination": "".join(str(d) for d in key), "digits": list(key)}
            else:
                item = {"rank": rank, "key": str(key)}
            item["count"] = count
            item["probability"] = _calc_probability(count, total_draws)
            result["items"].append(item)
        except Exception as e:
            logger.error(f"构建排行条目失败: key={key}({type(key).__name__}), count={count}, error={e}")
            continue
        rank += 1

    logger.info(f"排行结果: {len(result['items'])} 条 (page={page}, total={total_combos}, draws={total_draws})")
    return result


# ============================================================
# 1. 双号组合排行（3D/P3）
# ============================================================
def get_double_digit_ranking(lottery_code, mode="any", position_pair=None,
                              page=1, page_size=50, date_from=None, date_to=None):
    """双号组合出现频率排行"""
    if lottery_code not in ("3d", "p3"):
        return None

    position_names = {
        (0, 1): "百位+十位", (1, 2): "十位+个位", (0, 2): "百位+个位",
    }
    all_nums = _load_all_numbers(lottery_code, date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    if mode == "any":
        for nums in all_nums:
            if not isinstance(nums, list) or len(nums) != 3:
                continue
            a, b, c = sorted(nums)
            # 所有无序对
            for p in [(a, b), (a, c), (b, c)]:
                counter[p] += 1
    elif mode == "position":
        if position_pair not in position_names:
            position_pair = (0, 1)
        for nums in all_nums:
            if not isinstance(nums, list) or len(nums) < 3:
                continue
            i, j = position_pair
            counter[(nums[i], nums[j])] += 1

    # 转换 counter 为可序列化格式
    wrapped = Counter()
    for (d1, d2), cnt in counter.items():
        wrapped[(f"{d1}{d2}",)] = cnt

    def _items_from_counter(c, offset, psize):
        sorted_c = sorted(c.items(), key=lambda x: (-x[1], x[0]))
        page_c = sorted_c[offset:offset + psize]
        items = []
        rank = offset + 1
        for (combo,), cnt in page_c:
            items.append({
                "rank": rank,
                "combination": combo,
                "digits": [int(d) for d in combo],
                "count": cnt,
                "probability": _calc_probability(cnt, total_draws),
            })
            rank += 1
        return items

    total_combos = len(wrapped)
    offset = (page - 1) * page_size
    total_pages = max(1, (total_combos + page_size - 1) // page_size)

    return {
        "items": _items_from_counter(wrapped, offset, page_size),
        "total": total_combos,
        "total_draws": total_draws,
        "current_page": page,
        "total_pages": total_pages,
        "mode": mode,
        "position_pair": list(position_pair) if position_pair else None,
        "position_label": position_names.get(tuple(position_pair) if position_pair else (0, 1), "") if mode == "position" else "",
    }


# ============================================================
# 2. 三号组选排行（3D/P3）
# ============================================================
def get_triple_group_ranking(lottery_code, page=1, page_size=50,
                              date_from=None, date_to=None):
    """三号组选号码出现频率排行"""
    if lottery_code not in ("3d", "p3"):
        return None

    all_nums = _load_all_numbers(lottery_code, date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    for nums in all_nums:
        if not isinstance(nums, list) or len(nums) != 3:
            continue
        key = tuple(sorted(nums))
        counter[key] += 1

    sorted_items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    total_combos = len(sorted_items)
    offset = (page - 1) * page_size
    page_items = sorted_items[offset:offset + page_size]
    total_pages = max(1, (total_combos + page_size - 1) // page_size)

    items = []
    rank = offset + 1
    for combo, cnt in page_items:
        unique_digits = len(set(combo))
        if unique_digits == 1:
            gt = "豹子"
        elif unique_digits == 2:
            gt = "组三"
        else:
            gt = "组六"
        items.append({
            "rank": rank,
            "combination": "".join(str(d) for d in combo),
            "digits": list(combo),
            "count": cnt,
            "probability": _calc_probability(cnt, total_draws),
            "group_type": gt,
        })
        rank += 1

    return {
        "items": items, "total": total_combos, "total_draws": total_draws,
        "current_page": page, "total_pages": total_pages,
    }


# ============================================================
# 3. 排列五尾号排行
# ============================================================
def get_p5_tail_ranking(page=1, page_size=50, date_from=None, date_to=None):
    """排列五尾号出现频率排行"""
    all_nums = _load_all_numbers("p5", date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    for nums in all_nums:
        if not isinstance(nums, list) or len(nums) != 5:
            continue
        tail = (nums[3], nums[4])
        counter[tail] += 1

    sorted_items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))
    total_combos = len(sorted_items)
    offset = (page - 1) * page_size
    page_items = sorted_items[offset:offset + page_size]
    total_pages = max(1, (total_combos + page_size - 1) // page_size)

    items = []
    rank = offset + 1
    for tail, cnt in page_items:
        items.append({
            "rank": rank,
            "combination": f"{tail[0]}{tail[1]}",
            "digits": list(tail),
            "count": cnt,
            "probability": _calc_probability(cnt, total_draws),
        })
        rank += 1

    return {
        "items": items, "total": total_combos, "total_draws": total_draws,
        "current_page": page, "total_pages": total_pages,
    }


# ============================================================
# 4. 双色球 & 大乐透 蓝/红号排行
# ============================================================
def get_blue_ranking(lottery_code, page=1, page_size=50, date_from=None, date_to=None):
    """蓝球(后区)号码出现频率排行"""
    if lottery_code not in ("ssq", "dlt"):
        return None

    all_nums = _load_all_numbers(lottery_code, date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    for nums in all_nums:
        if not isinstance(nums, dict):
            continue
        if lottery_code == "ssq":
            blue = nums.get("blue")
            if blue is not None:
                counter[blue] += 1
        elif lottery_code == "dlt":
            back = nums.get("back", [])
            if isinstance(back, list):
                for b in back:
                    counter[b] += 1

    label = "蓝球" if lottery_code == "ssq" else "后区"
    return _build_paginated_result(counter, total_draws, page, page_size, {"label": label})


def get_red_ranking(lottery_code, page=1, page_size=50, date_from=None, date_to=None):
    """红球(前区)号码出现频率排行"""
    if lottery_code not in ("ssq", "dlt"):
        return None

    all_nums = _load_all_numbers(lottery_code, date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    for nums in all_nums:
        if not isinstance(nums, dict):
            continue
        if lottery_code == "ssq":
            red = nums.get("red", [])
            if isinstance(red, list):
                for r in red:
                    counter[r] += 1
        elif lottery_code == "dlt":
            front = nums.get("front", [])
            if isinstance(front, list):
                for f in front:
                    counter[f] += 1

    label = "红球" if lottery_code == "ssq" else "前区"
    return _build_paginated_result(counter, total_draws, page, page_size, {"label": label})


# ============================================================
# 5. 快乐八号码排行
# ============================================================
def get_kl8_number_ranking(page=1, page_size=50, date_from=None, date_to=None):
    """快乐八号码出现频率排行"""
    all_nums = _load_all_numbers("kl8", date_from, date_to)
    total_draws = len(all_nums)
    if total_draws == 0:
        return _build_paginated_result(Counter(), 0, page, page_size)

    counter = Counter()
    for nums in all_nums:
        if not isinstance(nums, list):
            continue
        for n in nums:
            counter[n] += 1

    return _build_paginated_result(counter, total_draws, page, page_size)


# ============================================================
# 6. 自定义出现次数查询
# ============================================================
def query_number_count(lottery_code, ranking_type, query_value,
                       mode="any", position="0,1", date_from=None, date_to=None):
    """根据用户输入的数值和选择的分类，查询对应项目的出现次数

    Args:
        lottery_code: 彩票代码
        ranking_type: 排行类型 (double/triple/tail/blue/red/number)
        query_value: 用户输入的查询值，如 "21", "135", "01" 等
        mode: 双号组合模式 (any/position)
        position: 双号组合位置
        date_from/date_to: 日期筛选

    Returns:
        dict: {"found": bool, "count": int, "probability": float, "item": dict, "total_draws": int}
    """
    result = {"found": False, "count": 0, "probability": 0, "item": None, "total_draws": 0}
    all_nums = _load_all_numbers(lottery_code, date_from, date_to)
    total_draws = len(all_nums)
    result["total_draws"] = total_draws
    if total_draws == 0:
        return result

    if ranking_type in ("blue", "red", "number"):
        # 单号查询
        try:
            qv = int(query_value)
        except ValueError:
            return result

        if ranking_type == "blue":
            if lottery_code not in ("ssq", "dlt"):
                return result
            counter = Counter()
            for nums in all_nums:
                if not isinstance(nums, dict):
                    continue
                if lottery_code == "ssq":
                    b = nums.get("blue")
                    if b == qv:
                        counter[b] += 1
                elif lottery_code == "dlt":
                    back = nums.get("back", [])
                    if isinstance(back, list) and qv in back:
                        counter[qv] += 1
            cnt = counter.get(qv, 0)
            result["found"] = cnt > 0
            result["count"] = cnt
            result["probability"] = _calc_probability(cnt, total_draws)
            result["item"] = {"number": qv, "count": cnt, "probability": result["probability"]}

        elif ranking_type == "red":
            if lottery_code not in ("ssq", "dlt"):
                return result
            counter = Counter()
            for nums in all_nums:
                if not isinstance(nums, dict):
                    continue
                if lottery_code == "ssq":
                    red = nums.get("red", [])
                    if isinstance(red, list) and qv in red:
                        counter[qv] += 1
                elif lottery_code == "dlt":
                    front = nums.get("front", [])
                    if isinstance(front, list) and qv in front:
                        counter[qv] += 1
            cnt = counter.get(qv, 0)
            result["found"] = cnt > 0
            result["count"] = cnt
            result["probability"] = _calc_probability(cnt, total_draws)
            result["item"] = {"number": qv, "count": cnt, "probability": result["probability"]}

        elif ranking_type == "number":
            if lottery_code != "kl8":
                return result
            counter = Counter()
            for nums in all_nums:
                if not isinstance(nums, list):
                    continue
                if qv in nums:
                    counter[qv] += 1
            cnt = counter.get(qv, 0)
            result["found"] = cnt > 0
            result["count"] = cnt
            result["probability"] = _calc_probability(cnt, total_draws)
            result["item"] = {"number": qv, "count": cnt, "probability": result["probability"]}

    elif ranking_type == "triple":
        # 三号组选查询
        if lottery_code not in ("3d", "p3"):
            return result
        try:
            digits = [int(d) for d in query_value.strip()]
        except (ValueError, TypeError):
            return result
        key = tuple(sorted(digits))
        counter = Counter()
        for nums in all_nums:
            if not isinstance(nums, list) or len(nums) != 3:
                continue
            gk = tuple(sorted(nums))
            if gk == key:
                counter[gk] += 1
        cnt = counter.get(key, 0)
        unique_digits = len(set(key))
        if unique_digits == 1:
            gt = "豹子"
        elif unique_digits == 2:
            gt = "组三"
        else:
            gt = "组六"
        result["found"] = cnt > 0
        result["count"] = cnt
        result["probability"] = _calc_probability(cnt, total_draws)
        result["item"] = {
            "combination": "".join(str(d) for d in key),
            "digits": list(key),
            "count": cnt,
            "probability": result["probability"],
            "group_type": gt,
        }

    elif ranking_type == "tail":
        # 尾号查询
        if lottery_code != "p5":
            return result
        try:
            d1 = int(query_value[0]) if len(query_value) > 0 else None
            d2 = int(query_value[1]) if len(query_value) > 1 else None
        except (ValueError, IndexError):
            return result
        if d1 is None or d2 is None:
            return result
        tail_key = (d1, d2)
        counter = Counter()
        for nums in all_nums:
            if not isinstance(nums, list) or len(nums) != 5:
                continue
            tail = (nums[3], nums[4])
            if tail == tail_key:
                counter[tail] += 1
        cnt = counter.get(tail_key, 0)
        result["found"] = cnt > 0
        result["count"] = cnt
        result["probability"] = _calc_probability(cnt, total_draws)
        result["item"] = {
            "combination": f"{d1}{d2}",
            "digits": [d1, d2],
            "count": cnt,
            "probability": result["probability"],
        }

    elif ranking_type == "double":
        # 双号组合查询
        if lottery_code not in ("3d", "p3"):
            return result
        try:
            d1 = int(query_value[0]) if len(query_value) > 0 else None
            d2 = int(query_value[1]) if len(query_value) > 1 else None
        except (ValueError, IndexError):
            return result
        if d1 is None or d2 is None:
            return result

        if mode == "any":
            # 不限位置：查询包含这两个数字的号码
            counter = Counter()
            for nums in all_nums:
                if not isinstance(nums, list) or len(nums) != 3:
                    continue
                sorted_nums = sorted(nums)
                pairs = set()
                for i in range(3):
                    for j in range(i + 1, 3):
                        pairs.add((sorted_nums[i], sorted_nums[j]))
                if (min(d1, d2), max(d1, d2)) in pairs:
                    counter[(d1, d2)] += 1
            cnt = counter.get((d1, d2), 0)
            result["found"] = cnt > 0
            result["count"] = cnt
            result["probability"] = _calc_probability(cnt, total_draws)
            result["item"] = {
                "combination": f"{d1}{d2}",
                "digits": [d1, d2],
                "count": cnt,
                "probability": result["probability"],
            }
        elif mode == "position":
            # 限制位置
            parts = position.split(",")
            if len(parts) != 2:
                return result
            i, j = int(parts[0]), int(parts[1])
            counter = Counter()
            for nums in all_nums:
                if not isinstance(nums, list) or len(nums) < 3:
                    continue
                if nums[i] == d1 and nums[j] == d2:
                    counter[(d1, d2)] += 1
            cnt = counter.get((d1, d2), 0)
            result["found"] = cnt > 0
            result["count"] = cnt
            result["probability"] = _calc_probability(cnt, total_draws)
            result["item"] = {
                "combination": f"{d1}{d2}",
                "digits": [d1, d2],
                "count": cnt,
                "probability": result["probability"],
            }

    return result


# ============================================================
# 排行类型配置表
# ============================================================
RANKING_TYPES = {
    "3d": [
        ("double", "双号组合排行", "统计两位数字组合出现频率"),
        ("triple", "三号组选排行", "组选模式（121/112/211 视为同一组合）"),
    ],
    "p3": [
        ("double", "双号组合排行", "统计两位数字组合出现频率"),
        ("triple", "三号组选排行", "组选模式（121/112/211 视为同一组合）"),
    ],
    "p5": [
        ("tail", "尾号排行", "统计后两位尾号组合出现频率"),
    ],
    "ssq": [
        ("blue", "蓝号排行", "统计蓝球号码出现频率"),
        ("red", "红号排行", "统计红球号码出现频率"),
    ],
    "dlt": [
        ("blue", "后区排行", "统计后区号码出现频率"),
        ("red", "前区排行", "统计前区号码出现频率"),
    ],
    "kl8": [
        ("number", "号码排行", "统计所有号码出现频率"),
    ],
}
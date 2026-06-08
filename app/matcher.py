"""号码匹配算法模块 - 提供多种号码匹配模式"""

# 单数字彩种（每位只需1位数字，无需zfill补零）
SINGLE_DIGIT_TYPES = {"3d", "p3", "p5", "qxc"}


def _fmt(n, code):
    """根据彩种决定数字格式化方式"""
    if code in SINGLE_DIGIT_TYPES:
        return str(n)
    return str(n).zfill(2)


def extract_number_string(lottery_code, numbers_json):
    """从JSON号码数据中提取纯数字字符串（用于直选匹配）"""
    nums = numbers_json
    if isinstance(nums, list):
        return "".join(_fmt(n, lottery_code) for n in nums)
    elif isinstance(nums, dict):
        if "red" in nums:
            return "".join(_fmt(n, lottery_code) for n in nums["red"])
        if "front" in nums:
            return "".join(_fmt(n, lottery_code) for n in nums["front"])
        if "main" in nums:
            return "".join(_fmt(n, lottery_code) for n in nums["main"])
    return ""


def extract_sorted_string(lottery_code, numbers_json):
    """提取排序后的数字字符串（用于组选匹配）"""
    nums = numbers_json
    if isinstance(nums, list):
        sorted_nums = sorted(nums)
        return "".join(_fmt(n, lottery_code) for n in sorted_nums)
    elif isinstance(nums, dict):
        if "red" in nums:
            sorted_nums = sorted(nums["red"])
            return "".join(_fmt(n, lottery_code) for n in sorted_nums)
        if "front" in nums:
            sorted_nums = sorted(nums["front"])
            return "".join(_fmt(n, lottery_code) for n in sorted_nums)
        if "main" in nums:
            sorted_nums = sorted(nums["main"])
            return "".join(_fmt(n, lottery_code) for n in sorted_nums)
    return ""


def wildcard_match(draw_nums, query_with_wildcards):
    """通配符匹配：None 位置匹配任意值"""
    if not isinstance(draw_nums, list) or not isinstance(query_with_wildcards, list):
        return False
    if len(query_with_wildcards) != len(draw_nums):
        return False
    for q, d in zip(query_with_wildcards, draw_nums):
        if q is not None and q != d:
            return False
    return True


def prefix_match(draw_nums, query_numbers):
    """前缀匹配：检查开奖号码是否以查询号码开头"""
    if not isinstance(draw_nums, list):
        return False
    if len(query_numbers) > len(draw_nums) or len(query_numbers) == 0:
        return False
    return draw_nums[:len(query_numbers)] == query_numbers


def match_list(draw_nums, query_numbers, search_type):
    """匹配简单列表类型 (3d/p3/p5/qxc/kl8)"""
    if not isinstance(draw_nums, list):
        return False
    if search_type == "direct":
        return draw_nums == query_numbers
    else:
        return sorted(draw_nums) == sorted(query_numbers)


def numbers_contains(draw_nums, query_numbers):
    """检查开奖号码是否包含所有查询号码（保留重复计数）

    如 query_numbers=[2,2] 则要求开奖号码中至少有2个2
    """
    if not isinstance(draw_nums, list):
        return False
    from collections import Counter
    draw_counter = Counter(draw_nums)
    query_counter = Counter(query_numbers)
    return all(draw_counter[k] >= v for k, v in query_counter.items())


def set_subset_match_mode(query_obj, lottery_code):
    """当查询数字少于完整组合时，设为子集包含匹配模式"""
    expected = {"ssq": 6, "dlt": 5, "7lc": 7}
    key_map = {"red_blue": "red", "front_back": "front", "main_special": "main"}
    key = key_map.get(query_obj.get("type", ""))
    if key and len(query_obj.get(key, [])) < expected.get(lottery_code, 99):
        query_obj["match_mode"] = "subset"


def match_dict(draw_nums, query_obj, search_type):
    """匹配字典类型 (ssq/dlt/7lc)

    match_mode:
    - "exact"（默认）：完整号码组精确匹配
    - "subset"：部分号码包含匹配（查询数字是开奖号码的子集）
    """
    if not isinstance(draw_nums, dict):
        return False

    match_mode = query_obj.get("match_mode", "exact")

    if "red" in draw_nums and query_obj.get("type") == "red_blue":
        draw_reds = sorted(draw_nums["red"])
        query_reds = query_obj["red"]
        if match_mode == "subset":
            red_ok = set(query_reds).issubset(draw_reds)
        else:
            red_ok = (draw_reds == query_reds)
        if query_obj.get("blue") is not None:
            blue_ok = (draw_nums.get("blue") == query_obj["blue"])
            return red_ok and blue_ok
        return red_ok

    elif "front" in draw_nums and query_obj.get("type") == "front_back":
        draw_front = sorted(draw_nums["front"])
        draw_back = sorted(draw_nums["back"])
        query_front = query_obj["front"]
        query_back = query_obj["back"]
        if match_mode == "subset":
            front_ok = set(query_front).issubset(draw_front)
        else:
            front_ok = (draw_front == query_front)
        back_ok = (not query_back or draw_back == query_back)
        return front_ok and back_ok

    elif "main" in draw_nums and query_obj.get("type") == "main_special":
        draw_main = sorted(draw_nums["main"])
        query_main = query_obj["main"]
        if match_mode == "subset":
            main_ok = set(query_main).issubset(draw_main)
        else:
            main_ok = (draw_main == query_main)
        if query_obj.get("special") is not None:
            special_ok = (draw_nums.get("special") == query_obj["special"])
            return main_ok and special_ok
        return main_ok

    return False
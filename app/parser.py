"""数据解析模块 - 解析各彩票类型的数据行"""

import json


def parse_line_3d(fields):
    """解析3D数据行 (17列)

    期号,日期,奖1,奖2,奖3,试1,试2,试3,机号,球号,
    投注总额,单选注数,单选金额,组三注数,组三金额,组六注数,组六金额
    """
    return {
        "numbers": [int(fields[2]), int(fields[3]), int(fields[4])],
        "trial_numbers": [int(fields[5]), int(fields[6]), int(fields[7])],
        "machine_ball": [int(fields[8]), int(fields[9])],
        "sale_amount": int(fields[10]),
        "prizes": [
            {"name": "单选", "count": int(fields[11]), "amount": int(fields[12])},
            {"name": "组三", "count": int(fields[13]), "amount": int(fields[14])},
            {"name": "组六", "count": int(fields[15]), "amount": int(fields[16])},
        ]
    }


def parse_line_p3(fields):
    """解析排列三数据行 (12列)"""
    return {
        "numbers": [int(fields[2]), int(fields[3]), int(fields[4])],
        "sale_amount": int(fields[5]),
        "prizes": [
            {"name": "直选", "count": int(fields[6]), "amount": int(fields[7])},
            {"name": "组三", "count": int(fields[8]), "amount": int(fields[9])},
            {"name": "组六", "count": int(fields[10]), "amount": int(fields[11])},
        ]
    }


def parse_line_p5(fields):
    """解析排列五数据行 (10列)"""
    return {
        "numbers": [int(fields[2]), int(fields[3]), int(fields[4]),
                    int(fields[5]), int(fields[6])],
        "sale_amount": int(fields[7]),
        "prizes": [
            {"name": "一等奖", "count": int(fields[8]), "amount": int(fields[9])},
        ]
    }


def parse_line_ssq(fields):
    """解析双色球数据行 (29列)

    期号,日期,红1-6(升序),蓝球, 红出球顺序1-6, 投注总额,奖池,
    一等注数,一等金额,二等注数,二等金额,...六等注数,六等金额
    """
    red_balls = [int(fields[2]), int(fields[3]), int(fields[4]),
                 int(fields[5]), int(fields[6]), int(fields[7])]
    blue_ball = int(fields[8])
    draw_order = [int(fields[9]), int(fields[10]), int(fields[11]),
                  int(fields[12]), int(fields[13]), int(fields[14])]

    return {
        "numbers": {"red": red_balls, "blue": blue_ball},
        "draw_order": draw_order,
        "sale_amount": int(fields[15]),
        "prize_pool": int(fields[16]),
        "prizes": [
            {"name": "一等奖", "count": int(fields[17]), "amount": int(fields[18])},
            {"name": "二等奖", "count": int(fields[19]), "amount": int(fields[20])},
            {"name": "三等奖", "count": int(fields[21]), "amount": int(fields[22])},
            {"name": "四等奖", "count": int(fields[23]), "amount": int(fields[24])},
            {"name": "五等奖", "count": int(fields[25]), "amount": int(fields[26])},
            {"name": "六等奖", "count": int(fields[27]), "amount": int(fields[28])},
        ]
    }


def parse_line_dlt(fields):
    """解析大乐透数据行 (36列)"""
    front = [int(fields[2]), int(fields[3]), int(fields[4]),
             int(fields[5]), int(fields[6])]
    back = [int(fields[7]), int(fields[8])]

    idx = 9
    sale_amount = int(fields[idx]); idx += 1
    prize_pool = int(fields[idx]); idx += 1

    prizes = []
    prize_names = ["一等奖", "二等奖", "三等奖", "四等奖",
                   "五等奖", "六等奖", "七等奖", "八等奖"]
    for name in prize_names:
        prizes.append({"name": name, "count": int(fields[idx]), "amount": int(fields[idx + 1])})
        idx += 2

    extra_prizes = []
    extra_names = ["追加一等奖", "追加二等奖", "追加三等奖"]
    for name in extra_names:
        extra_prizes.append({"name": name, "count": int(fields[idx]), "amount": int(fields[idx + 1])})
        idx += 2

    extra = {"extra_prizes": extra_prizes}
    if idx < len(fields):
        extra["附加投注总额"] = int(fields[idx])
        if idx + 1 < len(fields):
            extra["附加一等奖注数"] = int(fields[idx + 1])
        if idx + 2 < len(fields):
            extra["附加一等奖奖金"] = int(fields[idx + 2])

    return {
        "numbers": {"front": front, "back": back},
        "sale_amount": sale_amount,
        "prize_pool": prize_pool,
        "prizes": prizes,
        "extra": extra,
    }


def _safe_int(val, default=0):
    """安全转换为整数，无法转换时返回默认值"""
    try:
        v = int(val)
        return v
    except (ValueError, TypeError):
        return default


def parse_line_qxc(fields):
    """解析七星彩数据行 (23列)"""
    numbers = [int(fields[2]), int(fields[3]), int(fields[4]),
               int(fields[5]), int(fields[6]), int(fields[7]), int(fields[8])]

    return {
        "numbers": numbers,
        "sale_amount": _safe_int(fields[9]),
        "prize_pool": _safe_int(fields[10]),
        "prizes": [
            {"name": "特等奖", "count": _safe_int(fields[11]), "amount": _safe_int(fields[12])},
            {"name": "一等奖", "count": _safe_int(fields[13]), "amount": _safe_int(fields[14])},
            {"name": "二等奖", "count": _safe_int(fields[15]), "amount": _safe_int(fields[16])},
            {"name": "三等奖", "count": _safe_int(fields[17]), "amount": _safe_int(fields[18])},
            {"name": "四等奖", "count": _safe_int(fields[19]), "amount": _safe_int(fields[20])},
            {"name": "五等奖", "count": _safe_int(fields[21]), "amount": _safe_int(fields[22])},
        ]
    }


def parse_line_7lc(fields):
    """解析七乐彩数据行 (26列)"""
    numbers = [int(fields[2]), int(fields[3]), int(fields[4]),
               int(fields[5]), int(fields[6]), int(fields[7]), int(fields[8])]
    special = int(fields[9])

    return {
        "numbers": {"main": numbers, "special": special},
        "sale_amount": int(fields[10]),
        "prize_pool": int(fields[11]),
        "prizes": [
            {"name": "一等奖", "count": int(fields[12]), "amount": int(fields[13])},
            {"name": "二等奖", "count": int(fields[14]), "amount": int(fields[15])},
            {"name": "三等奖", "count": int(fields[16]), "amount": int(fields[17])},
            {"name": "四等奖", "count": int(fields[18]), "amount": int(fields[19])},
            {"name": "五等奖", "count": int(fields[20]), "amount": int(fields[21])},
            {"name": "六等奖", "count": int(fields[22]), "amount": int(fields[23])},
            {"name": "七等奖", "count": int(fields[24]), "amount": int(fields[25])},
        ]
    }


def parse_line_kl8(fields):
    """解析快乐八数据行 (122列)

    快乐八结构：期号,日期,20开奖号,20出球顺序,销售金额,奖池,
    然后选十~选一的各奖级注数和金额
    """
    numbers = [int(fields[i]) for i in range(2, 22)]
    draw_order = [int(fields[i]) for i in range(22, 42)]

    # 处理金额(可能含逗号)
    sale_str = fields[42].replace(",", "")
    pool_str = fields[43].replace(",", "")
    sale_amount = int(float(sale_str)) if sale_str else 0
    prize_pool = int(float(pool_str)) if pool_str else 0

    # 解析奖级
    prize_configs = [
        ("选十", ["中十", "中九", "中八", "中七", "中六", "中五", "中零"]),
        ("选九", ["中九", "中八", "中七", "中六", "中五", "中四", "中零"]),
        ("选八", ["中八", "中七", "中六", "中五", "中四", "中零"]),
        ("选七", ["中七", "中六", "中五", "中四", "中零"]),
        ("选六", ["中六", "中五", "中四", "中三"]),
        ("选五", ["中五", "中四", "中三"]),
        ("选四", ["中四", "中三", "中二"]),
        ("选三", ["中三", "中二"]),
        ("选二", ["中二"]),
        ("选一", ["中一"]),
    ]

    idx = 44
    prizes = []
    for game_name, levels in prize_configs:
        for level in levels:
            if idx < len(fields):
                count = int(float(fields[idx].replace(",", "")))
                idx += 1
            if idx < len(fields):
                amount_str = fields[idx].replace(",", "")
                amount = int(float(amount_str)) if amount_str else 0
                idx += 1
            prizes.append({"name": f"{game_name}{level}", "count": count, "amount": amount})

    return {
        "numbers": numbers,
        "draw_order": draw_order,
        "sale_amount": sale_amount,
        "prize_pool": prize_pool,
        "prizes": prizes,
    }


# 解析器映射表
PARSER_MAP = {
    "3d": parse_line_3d,
    "p3": parse_line_p3,
    "p5": parse_line_p5,
    "ssq": parse_line_ssq,
    "dlt": parse_line_dlt,
    "qxc": parse_line_qxc,
    "7lc": parse_line_7lc,
    "kl8": parse_line_kl8,
}


def parse_line(lottery_code, fields):
    """根据彩票类型解析一行数据

    Args:
        lottery_code: 彩票类型代码
        fields: 按空格分割后的字段列表

    Returns:
        解析后的字典，或None(失败时)
    """
    parser = PARSER_MAP.get(lottery_code)
    if not parser:
        return None
    try:
        return parser(fields)
    except (ValueError, IndexError) as e:
        print(f"[解析错误] {lottery_code} → {e} → fields: {fields}")
        return None


def format_numbers(numbers):
    """将号码格式化为可读字符串"""
    if isinstance(numbers, list):
        return " ".join(str(n).zfill(2) for n in numbers)
    elif isinstance(numbers, dict):
        parts = []
        if "red" in numbers or "front" in numbers:
            key = "red" if "red" in numbers else "front"
            parts.append(" ".join(str(n).zfill(2) for n in numbers[key]))
        if "blue" in numbers or "back" in numbers:
            key = "blue" if "blue" in numbers else "back"
            parts.append("+" + " ".join(str(n).zfill(2) for n in numbers[key]))
        if "main" in numbers:
            parts.append(" ".join(str(n).zfill(2) for n in numbers["main"]))
            parts.append(f"特别号:{numbers.get('special', '')}")
        return " ".join(parts)
    return str(numbers)
"""工具定义与执行

20 个工具映射到现有 API 端点。
使用 OpenAI Function Calling 格式注册。
内部通过 httpx 调用本地 API。
"""

import json
import httpx
from app import config

# ============================================================
# 工具定义（OpenAI Function Calling 格式）
# ============================================================

# 所有彩种列表常量（减少枚举重复）
ALL_LOTTERIES = ["3d", "p3", "p5", "ssq", "dlt", "kl8", "qxc", "7lc"]
DIGIT_LOTTERIES = ["3d", "p3", "p5"]

_RAW_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_latest_draws",
            "description": "获取最新开奖号码（可选彩种）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种，不传则获取全部",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_draw_by_number",
            "description": "按期号查询单期开奖（支持短号模糊匹配，如318可匹配2025318）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "draw_number": {
                        "type": "string",
                        "description": "期号（支持短号，如318）",
                    },
                },
                "required": ["lottery_code", "draw_number"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_number_stats",
            "description": "查询单个号码的直选和组选出现次数",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "number": {
                        "type": "string",
                        "description": "要查询的号码，如311",
                    },
                },
                "required": ["lottery_code", "number"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "batch_get_number_stats",
            "description": "批量查询多个号码的直选+组选次数（一次查询比逐个更快）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "numbers": {
                        "type": "string",
                        "description": "号码列表用逗号分隔，如111,222,333",
                    },
                },
                "required": ["lottery_code", "numbers"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_number",
            "description": "搜索号码的历史开奖记录（含日期和期号），适合查询具体开出时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索号码",
                    },
                },
                "required": ["lottery_code", "query"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_unused_numbers",
            "description": "查询从未开出的号码列表（仅3D/排列三/排列五）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": DIGIT_LOTTERIES,
                        "description": "彩种",
                    },
                    "year_range": {
                        "type": "string",
                        "enum": ["all", "1y", "6m", "3m", "1m", "1w"],
                        "description": "时间范围，默认all",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_draws_by_date",
            "description": "按日期范围查询开奖数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "起始日期 YYYY-MM-DD",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期 YYYY-MM-DD",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_draws_by_period",
            "description": "按时间段或期号范围查询开奖数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "period": {
                        "type": "string",
                        "enum": ["1w", "1m", "6m", "1y", "3y", "10y", "all"],
                        "description": "预设时间段：1w=近一周 1m=近一月 6m=近半年 1y=近一年",
                    },
                    "draw_from": {
                        "type": "string",
                        "description": "起始期号（可选）",
                    },
                    "draw_to": {
                        "type": "string",
                        "description": "结束期号（可选）",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_group_selection_stats",
            "description": "组选查询统计，支持通配符如'1 空 2'（百位1十位任意个位2）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": DIGIT_LOTTERIES,
                        "description": "彩种（仅3D/排列三/排列五）",
                    },
                    "number": {
                        "type": "string",
                        "description": "号码，支持'1 空 2'通配格式或纯号码如123",
                    },
                    "search_type": {
                        "type": "string",
                        "enum": ["group", "direct"],
                        "description": "group=组选 direct=直选",
                    },
                },
                "required": ["lottery_code", "number"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_complex_stats",
            "description": "复杂条件统计：和值/奇偶比/大小比/跨度。如'和值为8的号码出现次数'",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "query_value": {
                        "type": "string",
                        "description": "查询值，如'8'表示和值=8，'3-5'表范围",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["sum", "odd_even", "big_small", "span", "any"],
                        "description": "sum=和值 odd_even=奇偶 big_small=大小 span=跨度",
                    },
                    "position": {
                        "type": "string",
                        "description": "位置如'0,1'（3D适用）",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "起始日期（可选）",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "结束日期（可选）",
                    },
                },
                "required": ["lottery_code", "query_value"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_kl8_data",
            "description": "快乐八专项查询：号码排行/分组统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_type": {
                        "type": "string",
                        "enum": ["ranking", "grouped_stats", "number_history"],
                        "description": "ranking=排行 grouped_stats=分组 number_history=历史",
                    },
                    "query_value": {
                        "type": "string",
                        "description": "号码（number_history时必填）",
                    },
                },
                "required": ["data_type"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_number_history",
            "description": "号码在各历史时间段的出现记录（热号冷号分析）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "number": {
                        "type": "string",
                        "description": "号码",
                    },
                    "num_type": {
                        "type": "string",
                        "enum": ["single", "group"],
                        "description": "single=单个 group=组选",
                    },
                },
                "required": ["lottery_code", "number"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_history_draws",
            "description": "获取历史开奖列表（分页）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码",
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_countdown",
            "description": "获取下一期开奖倒计时",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_lottery_schedule",
            "description": "获取彩种的开奖时间配置",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_stats",
            "description": "获取系统总体统计（总开奖数等）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_period_stats",
            "description": "获取彩种各时间段开奖期数统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_history",
            "description": "获取[历史的今天]数据（今天日期历史上开出的号码）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_ranking",
            "description": "获取彩种排行分析数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                    "ranking_type": {
                        "type": "string",
                        "enum": ["double", "triple", "tail", "blue", "red", "number"],
                        "description": "double=双号 triple=三号 tail=尾号 blue=蓝球 red=红球 number=号码",
                    },
                },
                "required": ["lottery_code", "ranking_type"],
                "additionalProperties": False,
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_grouped_stats",
            "description": "号码按出现次数分组统计（适用组合彩种）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lottery_code": {
                        "type": "string",
                        "enum": ALL_LOTTERIES,
                        "description": "彩种",
                    },
                },
                "required": ["lottery_code"],
                "additionalProperties": False,
            },
        }
    },
]

def _get_strict_setting() -> bool:
    """根据配置决定是否启用 Strict 模式"""
    return config.DEEPSEEK_USE_BETA

def _build_tool_definitions() -> list:
    """生成工具定义列表，按配置动态添加 strict 字段"""
    return [
        {
            "type": "function",
            "function": {
                **(
                    {"strict": True} if _get_strict_setting() else {}
                ),
                **{k: v for k, v in func_def["function"].items() if k != "strict"},
            }
        }
        for func_def in _RAW_TOOL_DEFINITIONS
    ]

TOOL_DEFINITIONS = _build_tool_definitions()

# 工具名称 → API 路径映射
TOOL_API_MAP = {
    "get_latest_draws": "/{code}/latest",
    "get_draw_by_number": "/{code}/draw/{draw_number}",
    "get_number_stats": "/{code}/batch-number-stats?numbers={number}",
    "batch_get_number_stats": "/{code}/batch-number-stats?numbers={numbers}",
    "get_unused_numbers": "/{code}/unused-numbers?year_range={year_range}",
    "search_number": "/{code}/search-number?q={query}",
    "get_draws_by_date": "/draws/{code}?start_date={start_date}&end_date={end_date}&limit=50",
    "get_draws_by_period": "/{code}/draws/period?period={period}&draw_from={draw_from}&draw_to={draw_to}&page_size=50",
    "get_group_selection_stats": "/{code}/search-number?q={number}&search_type={search_type}",
    "get_complex_stats": "/{code}/ranking/query?query_value={query_value}&mode={mode}&position={position}&date_from={date_from}&date_to={date_to}",
    "get_kl8_data": "/{code}/ranking/{data_type}",
    "get_number_history": "/{code}/number-history?q={number}&num_type={num_type}",
    "get_history_draws": "/draws/{code}?page={page}&page_size={page_size}",
    "get_countdown": "/countdown",
    "get_lottery_schedule": "/{code}/schedule",
    "get_system_stats": "/stats/system",
    "get_period_stats": "/{code}/period-stats",
    "get_today_history": "/{code}/today-history",
    "get_ranking": "/{code}/ranking/{ranking_type}",
    "get_grouped_stats": "/{code}/stats/grouped",
}


async def execute_tool(name: str, args: dict) -> dict:
    """执行工具调用

    Args:
        name: 工具名称
        args: 工具参数

    Returns:
        API 返回的数据
    """
    path_template = TOOL_API_MAP.get(name)
    if not path_template:
        return {"error": f"未知工具: {name}"}

    # 构建路径 - 特殊处理不需要 lottery_code 的工具
    if name in ("get_countdown", "get_system_stats"):
        path = path_template
    elif name == "get_kl8_data":
        # 快乐八数据查询固定 code 为 kl8
        code = "kl8"
        data_type = args.pop("data_type", "ranking")
        query_value = args.pop("query_value", "")
        path = path_template.format(code=code, data_type=data_type)
        # 对于 number_history 类型，通过不同端点查询
        if data_type == "number_history" and query_value:
            api_base = f"http://127.0.0.1:{config.SERVER_PORT}/api"
            async with httpx.AsyncClient(base_url=api_base, timeout=15) as client:
                resp = await client.get(f"/kl8/number-history?q={query_value}&num_type=single")
                if resp.status_code != 200:
                    return {"error": f"API 返回 {resp.status_code}", "detail": resp.text[:500]}
                return resp.json()
        else:
            api_base = f"http://127.0.0.1:{config.SERVER_PORT}/api"
            async with httpx.AsyncClient(base_url=api_base, timeout=15) as client:
                resp = await client.get(path)
                if resp.status_code != 200:
                    return {"error": f"API 返回 {resp.status_code}", "detail": resp.text[:500]}
                return resp.json()
    else:
        code = args.pop("lottery_code", "")
        # 处理可选参数，缺失的用空字符串
        formatted_args = {}
        for key in list(args.keys()):
            if args[key] is None:
                formatted_args[key] = ""
            else:
                formatted_args[key] = args[key]

        # 特殊处理 get_draws_by_date: start_date/end_date 可能为空
        if name == "get_draws_by_date":
            start = formatted_args.get("start_date", "")
            end = formatted_args.get("end_date", "")
            path = f"/draws/{code}?limit=50"
            if start:
                path += f"&start_date={start}"
            if end:
                path += f"&end_date={end}"
        elif name == "get_draws_by_period":
            period = formatted_args.get("period", "all")
            draw_from = formatted_args.get("draw_from", "")
            draw_to = formatted_args.get("draw_to", "")
            path = f"/{code}/draws/period?period={period}&page_size=50"
            if draw_from:
                path += f"&draw_from={draw_from}"
            if draw_to:
                path += f"&draw_to={draw_to}"
        elif name == "get_complex_stats":
            qv = formatted_args.get("query_value", "")
            mode = formatted_args.get("mode", "any")
            pos = formatted_args.get("position", "0,1")
            df = formatted_args.get("date_from", "")
            dt = formatted_args.get("date_to", "")
            path = f"/{code}/ranking/query?query_value={qv}&mode={mode}&position={pos}"
            if df:
                path += f"&date_from={df}"
            if dt:
                path += f"&date_to={dt}"
        elif name == "get_group_selection_stats":
            number = formatted_args.get("number", "")
            search_type = formatted_args.get("search_type", "group")
            path = f"/{code}/search-number?q={number}&search_type={search_type}"
        elif name == "get_number_stats":
            # 单号码查询，从 batch 结果中提取第一条
            number = formatted_args.get("number", "")
            path = f"/{code}/batch-number-stats?numbers={number}"
        else:
            path = path_template.format(code=code, **formatted_args)

    # 调用本地 API
    api_base = f"http://127.0.0.1:{config.SERVER_PORT}/api"
    async with httpx.AsyncClient(base_url=api_base, timeout=15) as client:
        resp = await client.get(path)
        if resp.status_code != 200:
            return {"error": f"API 返回 {resp.status_code}", "detail": resp.text[:500]}
        data = resp.json()

    # 精简返回数据（避免过长）
    if name == "get_number_stats":
        # 单号码查询：从 batch 结果列表中提取第一个元素
        if isinstance(data, dict) and "data" in data:
            items = data["data"]
            if isinstance(items, list) and len(items) > 0:
                return items[0]
        return data

    if isinstance(data, dict) and "data" in data:
        result = data["data"]
        if isinstance(result, list) and len(result) > 50:
            result = result[:50]
            result.append({"note": f"... 仅显示前50条，共 {len(data['data'])} 条"})
        return result

    if isinstance(data, dict) and "draws" in data:
        draws = data["draws"]
        if isinstance(draws, list) and len(draws) > 30:
            draws = draws[:30]
        return {"draws": draws, "total": data.get("total", 0)}

    return data
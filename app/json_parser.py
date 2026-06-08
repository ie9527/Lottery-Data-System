"""JSON API 号码解析模块"""

import json


def parse_json_numbers(lotid, api_data):
    """根据彩种类型解析JSON API中的号码数据为数据库格式

    Args:
        lotid: JSON API中的lotid
        api_data: 该彩种的JSON数据

    Returns:
        dict 或 None（解析失败）
    """
    winnum = api_data.get("winnum", "")

    try:
        if lotid == "3d":
            nums = [int(x) for x in winnum.split(",")]
            trial = None
            sjh_red = api_data.get("sjh_red")
            if sjh_red:
                trial = [int(x) for x in sjh_red]
            return {
                "numbers": json.dumps(nums),
                "trial_numbers": json.dumps(trial) if trial else None,
                "draw_order": None,
            }

        elif lotid == "pl3":
            nums = [int(x) for x in winnum.split(",")]
            trial = None
            sjh_red = api_data.get("sjh_red")
            if sjh_red:
                trial = [int(x) for x in sjh_red]
            return {
                "numbers": json.dumps(nums),
                "trial_numbers": json.dumps(trial) if trial else None,
                "draw_order": None,
            }

        elif lotid == "pl5":
            nums = [int(x) for x in winnum.split(",")]
            trial = None
            sjh_red = api_data.get("sjh_red")
            if sjh_red:
                trial = [int(x) for x in sjh_red]
            return {
                "numbers": json.dumps(nums),
                "trial_numbers": json.dumps(trial) if trial else None,
                "draw_order": None,
            }

        elif lotid == "ssq":
            parts = winnum.split("|")
            red = [int(x) for x in parts[0].split(",")]
            blue = int(parts[1])
            result = {"numbers": json.dumps({"red": red, "blue": blue})}

            sjh_red = api_data.get("sjh_red")
            sjh_blue = api_data.get("sjh_blue")
            if sjh_red and sjh_blue:
                trial = {"red": [int(x) for x in sjh_red], "blue": [int(x) for x in sjh_blue]}
                result["trial_numbers"] = json.dumps(trial)

            cq = api_data.get("cq")
            if cq:
                result["draw_order"] = json.dumps([int(x) for x in cq])

            return result

        elif lotid == "dlt":
            parts = winnum.split("|")
            front = [int(x) for x in parts[0].split(",")]
            back = [int(x) for x in parts[1].split(",")]
            result = {"numbers": json.dumps({"front": front, "back": back})}

            cq_red = api_data.get("cq_red")
            cq_blue = api_data.get("cq_blue")
            if cq_red and cq_blue:
                order = {"red": [int(x) for x in cq_red], "blue": [int(x) for x in cq_blue]}
                result["draw_order"] = json.dumps(order)

            return result

        elif lotid == "kl8":
            nums = [int(x) for x in winnum.split(",")]
            result = {"numbers": json.dumps(nums)}

            cq = api_data.get("cq")
            if cq:
                result["draw_order"] = json.dumps([int(x) for x in cq])

            return result

        elif lotid == "7lc":
            parts = winnum.split("|")
            main = [int(x) for x in parts[0].split(",")]
            special = int(parts[1])
            result = {"numbers": json.dumps({"main": main, "special": special})}

            cq = api_data.get("cq")
            if cq:
                result["draw_order"] = json.dumps([int(x) for x in cq])

            return result

        elif lotid == "7xc":
            red = api_data.get("red", [])
            blue = api_data.get("blue", [])
            if red and blue:
                nums = [int(x) for x in red] + [int(x) for x in blue]
            else:
                nums = [int(x) for x in winnum.split(",")]
            return {"numbers": json.dumps(nums), "trial_numbers": None, "draw_order": None}

        else:
            return None
    except (ValueError, IndexError, KeyError) as e:
        print(f"  [解析失败] {lotid}: {e} → winnum={winnum}")
        return None
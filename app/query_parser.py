"""号码查询解析模块 - 将查询字符串转为结构化查询对象"""

# 不可重复彩种集合（号码在同一区内不能重复）
UNIQUE_NUM_TYPES = {"ssq", "dlt", "7lc"}


def _deduplicate(nums):
    """对不可重复彩种的号码进行去重（保留顺序）"""
    seen = set()
    result = []
    for n in nums:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def parse_search_query(lottery_code, q: str):
    """将前端提交的查询字符串解析为结构化查询对象

    支持的格式（前端生成）：
    - 简单数字彩种 (3d/p3/p5/qxc):  "1,2,3" → 3个数字
    - 双色球 (ssq):                  "1,5,12,18,25,33|7" → 红球+蓝球
    - 大乐透 (dlt):                  "2,7,15,22,30|4,10" → 前区+后区
    - 七乐彩 (7lc):                  "3,7,8,11,14,21,30|19" → 基本号+特别号
    - 快乐八 (kl8):                  "3,15,22" → 任意数量的号码

    Returns:
        dict 或 None:
        - {type: "list", numbers: [int, ...]}
        - {type: "red_blue", red: [int, ...], blue: int|None}
        - {type: "front_back", front: [int, ...], back: [int, ...]}
        - {type: "main_special", main: [int, ...], special: int|None}
    """
    if not q or not q.strip():
        return None

    try:
        if lottery_code in ("3d", "p3", "p5", "qxc"):
            parts = q.split(",")
            nums = []
            has_wildcard = False
            for p in parts:
                p = p.strip()
                if p == "":
                    nums.append(None)
                    has_wildcard = True
                else:
                    nums.append(int(p))
            return {"type": "list", "numbers": nums, "has_wildcard": has_wildcard}

        elif lottery_code == "ssq":
            if "|" in q:
                left, right = q.split("|", 1)
                # 全部分类搜索：同时搜索红球和蓝球所有号码
                all_nums_str = left.replace("all:", "").split(",")
                reds = [int(x.strip()) for x in all_nums_str if x.strip()]
                blues = [int(x.strip()) for x in right.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    reds = _deduplicate(reds)
                return {"type": "red_blue", "red": sorted(reds), "blue": blues[0] if blues else None}
            else:
                parts = [int(x.strip()) for x in q.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    parts = _deduplicate(parts)
                return {"type": "red_blue", "red": sorted(parts), "blue": None}

        elif lottery_code == "dlt":
            if "|" in q:
                left, right = q.split("|", 1)
                # 全部分类搜索：同时搜索前区和后区所有号码
                if left.startswith("all:"):
                    all_nums_str = left[4:].split(",")
                    front = [int(x.strip()) for x in all_nums_str if x.strip()]
                    back = [int(x.strip()) for x in right.split(",") if x.strip()]
                    all_nums = sorted(front + back)
                    if lottery_code in UNIQUE_NUM_TYPES:
                        all_nums = _deduplicate(all_nums)
                    return {"type": "all", "numbers": all_nums}
                front = [int(x.strip()) for x in left.split(",") if x.strip()]
                back = [int(x.strip()) for x in right.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    front = _deduplicate(front)
                    back = _deduplicate(back)
                return {"type": "front_back", "front": sorted(front), "back": sorted(back)}
            else:
                parts = [int(x.strip()) for x in q.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    parts = _deduplicate(parts)
                return {"type": "front_back", "front": sorted(parts), "back": []}

        elif lottery_code == "7lc":
            if "|" in q:
                left, right = q.split("|", 1)
                main = [int(x.strip()) for x in left.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    main = _deduplicate(main)
                specials = [int(x.strip()) for x in right.split(",") if x.strip()]
                return {"type": "main_special", "main": sorted(main), "special": specials[0] if specials else None}
            else:
                parts = [int(x.strip()) for x in q.split(",") if x.strip()]
                if lottery_code in UNIQUE_NUM_TYPES:
                    parts = _deduplicate(parts)
                return {"type": "main_special", "main": sorted(parts), "special": None}

        elif lottery_code == "kl8":
            parts = [x.strip() for x in q.split(",") if x.strip()]
            nums = sorted([int(x) for x in parts])
            return {"type": "list", "numbers": nums}

    except (ValueError, IndexError):
        return None

    return None


def parse_query_for_template(lottery_code, q):
    """将查询字符串解析为模板回填用的结构化数据"""
    if not q:
        return None

    if lottery_code in ("ssq", "dlt", "7lc") and "|" in q:
        left, right = q.split("|", 1)
        if lottery_code == "ssq":
            # 补齐6个红球，不足的填空字符串
            reds = left.split(",")
            reds = reds[:6] + [''] * max(0, 6 - len(reds))
            return {"red": reds, "blue": right.split(",")}
        elif lottery_code == "dlt":
            front = left.split(",")
            front = front[:5] + [''] * max(0, 5 - len(front))
            return {"front": front, "back": right.split(",")}
        elif lottery_code == "7lc":
            main = left.split(",")
            main = main[:7] + [''] * max(0, 7 - len(main))
            return {"main": main, "special": right.split(",")}
    elif lottery_code in ("ssq", "dlt", "7lc"):
        # 无"|"分隔符时，尝试按对应格式解析
        parts = q.split(",")
        if lottery_code == "ssq":
            reds = parts[:6] + [''] * max(0, 6 - len(parts))
            return {"red": reds, "blue": []}
        elif lottery_code == "dlt":
            front = parts[:5] + [''] * max(0, 5 - len(parts))
            return {"front": front, "back": []}
        elif lottery_code == "7lc":
            main = parts[:7] + [''] * max(0, 7 - len(parts))
            return {"main": main, "special": []}
    else:
        return q.split(",")

    return None
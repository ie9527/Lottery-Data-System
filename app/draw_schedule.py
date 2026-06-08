"""开奖时间表与倒计时模块

所有开奖时间配置集中在 app/config.py -> DRAW_SCHEDULE 中，
修改开奖时间只需编辑 config.py，倒计时和自动更新自动同步。
"""

from datetime import datetime, date, timedelta, time
from typing import Optional
from app.config import POLL_START_HOUR, POLL_END_HOUR, POST_DRAW_DELAY
from app.config import DRAW_SCHEDULE

# 从配置文件读取开奖时间表
SCHEDULE = DRAW_SCHEDULE

# 时间常量
DAYS_CN = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}

# 全局时间窗口
POLL_START_HOUR = POLL_START_HOUR  # 21:00 前禁止读取
POLL_END_HOUR = POLL_END_HOUR      # 安全限制：最晚不超过 23:00
POST_DRAW_DELAY = POST_DRAW_DELAY  # 开奖后等待 N 分钟（直播结束）


def _get_draw_time(sched):
    """兼容处理：config中 time 存储为 "HH:MM" 字符串"""
    t = sched["time"]
    if isinstance(t, str):
        parts = t.split(":")
        return time(int(parts[0]), int(parts[1]))
    return t


def get_next_draw(code: str) -> Optional[datetime]:
    """计算指定彩种的下一次开奖时间"""
    sched = SCHEDULE.get(code)
    if not sched:
        return None

    draw_time = _get_draw_time(sched)
    now = datetime.now()
    today = now.date()

    # 今天是否开奖日，且开奖时间还没过？
    if now.weekday() in sched["days"]:
        draw_today = datetime.combine(today, draw_time)
        if now < draw_today:
            return draw_today

    # 找未来第一个开奖日（最多查14天）
    for ahead in range(1, 14):
        candidate = today + timedelta(days=ahead)
        if candidate.weekday() in sched["days"]:
            return datetime.combine(candidate, draw_time)

    return None


def get_all_countdowns():
    """获取所有彩种的倒计时信息"""
    now = datetime.now()
    result = {}

    for code in SCHEDULE:
        next_dt = get_next_draw(code)
        sched = SCHEDULE[code]
        draw_time = _get_draw_time(sched)
        if next_dt:
            seconds_left = int((next_dt - now).total_seconds())
            is_draw_day = now.weekday() in sched["days"]

            # 判断今日该彩种是否已过开奖时间
            today_draw_time = datetime.combine(now.date(), draw_time)
            is_today_draw_passed = is_draw_day and now >= today_draw_time

            # is_before_draw: 今日是开奖日且还未到开奖时间
            is_before_draw = is_draw_day and not is_today_draw_passed

            # is_after_draw: 今日是开奖日且今日开奖时间已过
            is_after_draw = is_today_draw_passed

            # 今日已过开奖时间 → seconds_left 置0
            if is_after_draw:
                display_seconds = 0
            else:
                display_seconds = max(0, seconds_left)

            result[code] = {
                "name": sched["name"],
                "next_draw": next_dt.strftime("%Y-%m-%d %H:%M"),
                "next_draw_ts": int(next_dt.timestamp()),
                "seconds_left": display_seconds,
                "is_draw_day": is_draw_day,
                "is_before_draw": is_before_draw,
                "is_after_draw": is_after_draw,
                "draw_time": draw_time.strftime("%H:%M"),
                "draw_days": sched["interval"],
                "draw_days_cn": ", ".join(
                    DAYS_CN[d] for d in sched["days"]
                ),
            }
        else:
            result[code] = {
                "name": sched["name"],
                "next_draw": None,
                "seconds_left": -1,
                "is_draw_day": False,
                "is_before_draw": False,
                "is_after_draw": False,
                "draw_time": draw_time.strftime("%H:%M"),
                "draw_days": sched["interval"],
                "draw_days_cn": "",
            }

    return result


def should_check_update(code: str, last_updated_date: Optional[str] = None) -> bool:
    """判断指定彩种当前是否应该检查更新

    规则（按优先级）：
    1. 今日已更新过该彩种 → 不检查
    2. 当前时间 < 21:00 → 不检查
    3. 当前时间 >= 23:00 → 不检查（安全限制）
    4. 今天非开奖日 → 不检查（隔日开奖彩种）
    5. 开奖时间过后不足8分钟 → 不检查（等待直播结束）
    6. 全部通过 → 可以检查
    """
    today_str = date.today().strftime("%Y-%m-%d")

    # 规则1：今日已更新
    if last_updated_date == today_str:
        return False

    now = datetime.now()
    sched = SCHEDULE.get(code)
    if not sched:
        return False

    # 规则2：21:00 前禁止读取
    if now.hour < POLL_START_HOUR:
        return False

    # 规则3：23:00 后停止读取（安全限制）
    if now.hour >= POLL_END_HOUR:
        return False

    # 规则4：非开奖日跳过（隔日开奖类型自动满足）
    if now.weekday() not in sched["days"]:
        return False

    # 规则5：开奖时间 + 8分钟延迟
    draw_time_today = datetime.combine(now.date(), _get_draw_time(sched))
    poll_start = draw_time_today + timedelta(minutes=POST_DRAW_DELAY)
    if now < poll_start:
        return False

    # 规则6：全部通过 → 可以检查
    return True
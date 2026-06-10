"""自动更新模块 - 从JSON接口增量更新数据"""

import json
from datetime import datetime, date, timedelta, time
from app.database import get_connection
from app.fetcher import fetch_json_api, JSON_LOTID_MAP, fetch_data, SYSTEM_TO_JSON
from app.stats_builder import build_number_stats
from app.draw_schedule import should_check_update
from app.json_parser import parse_json_numbers
from app.parser import parse_line, _safe_int
from app.logger import logger, log_update, log_polling


def do_json_update():
    """执行一次JSON API增量更新

    流程：
    1. 从JSON接口获取所有彩种最新数据
    2. 逐个与数据库对比期号
    3. 只写入比数据库更新的数据
    4. 重建被更新彩种的号码统计

    Returns:
        dict: {"total_added": int, "updates": {lottery_code: added_count}}
    """
    raw_data = fetch_json_api()
    if not raw_data:
        return {"total_added": 0, "updates": {}}

    conn = get_connection()
    cursor = conn.cursor()
    result = {"total_added": 0, "updates": {}}
    updated_codes = []

    for json_lotid, api_data in raw_data.items():
        # 映射到系统彩种代码
        db_code = JSON_LOTID_MAP.get(json_lotid)
        if not db_code:
            continue

        # 获取期号
        issue = api_data.get("issue")
        if not issue:
            continue

        # 检查是否已存在
        cursor.execute(
            "SELECT id FROM lottery_draws WHERE lottery_code=? AND draw_number=?",
            (db_code, str(issue))
        )
        if cursor.fetchone():
            # 已存在，跳过
            continue

        # 解析号码数据
        parsed = parse_json_numbers(json_lotid, api_data)
        if not parsed:
            continue

        # 转换时间戳
        kjdate = api_data.get("kjdate")
        if kjdate:
            draw_date = datetime.fromtimestamp(kjdate).strftime("%Y-%m-%d")
        else:
            draw_date = ""

        # 写入数据库
        cursor.execute("""
            INSERT OR IGNORE INTO lottery_draws
            (lottery_code, draw_number, draw_date, numbers, trial_numbers, machine_ball, draw_order, sale_amount, prize_pool, prizes, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            db_code,
            str(issue),
            draw_date,
            parsed["numbers"],
            parsed.get("trial_numbers"),
            None,
            parsed.get("draw_order"),
            None,
            None,
            None,
            None,
        ))

        if cursor.rowcount > 0:
            result["total_added"] += 1
            result["updates"][db_code] = result["updates"].get(db_code, 0) + 1
            updated_codes.append(db_code)
            print(f"  [新增] {db_code} 期 {issue} 日期 {draw_date}")
            logger.info(f"[新增] {db_code} 期 {issue} 日期 {draw_date}")

    # 记录更新日志
    if result["total_added"] > 0:
        for code, count in result["updates"].items():
            cursor.execute("""
                INSERT INTO update_log (lottery_code, status, records_added, message, operator)
                VALUES (?, 'success', ?, ?, 'auto_updater')
            """, (code, count, f"JSON接口自动更新，新增{count}条"))

        conn.commit()

        # 重建受影响彩种的号码统计
        for code in set(updated_codes):
            try:
                stats = build_number_stats(code)
                print(f"  [统计] {code}: {stats['direct_count']} 直选号码")
                logger.info(f"[统计] {code}: {stats['direct_count']} 直选号码")
            except Exception as e:
                print(f"  [统计失败] {code}: {e}")
                logger.error(f"[统计失败] {code}: {e}")

    conn.close()

    if result["total_added"] > 0:
        print(f"[更新完成] 共新增 {result['total_added']} 条记录")
        logger.info(f"[更新完成] 共新增 {result['total_added']} 条记录")
    else:
        print("[更新] 所有彩种数据已为最新")
        logger.info("[更新] 所有彩种数据已为最新")

    return result


def _check_sequence_gap(cursor, db_code: str) -> bool:
    """检查彩种期号是否存在断层

    如果数据库中最新的两条记录期号差值 > 1，说明存在断层。
    例如：最新=2026151，次新=2026149，差值=2 → 有断层（缺少2026150）

    Args:
        cursor: 数据库游标
        db_code: 彩种代码

    Returns:
        True=存在断层（需要补齐），False=连续或无法判断
    """
    cursor.execute(
        "SELECT draw_number FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC LIMIT 2",
        (db_code,)
    )
    rows = cursor.fetchall()
    if len(rows) < 2:
        return False
    try:
        latest = int(rows[0]["draw_number"])
        second = int(rows[1]["draw_number"])
        has_gap = (latest - second) > 1
        if has_gap:
            print(f"  [连续性检测] {db_code}: 最新={latest}, 次新={second}, 断层={latest-second-1}期")
        return has_gap
    except (ValueError, TypeError):
        return False


def catch_up_missing(force=False):
    """断服补数据 - 检测并补齐服务器离线期间遗漏的开奖数据

    流程：
    1. 获取 JSON API 最新数据
    2. 对每个彩种，检查数据库最新日期与 API 最新日期的差距
    3. 若差距超过预期间隔，下载 TXT 历史文件补齐缺失数据
    4. 使用 INSERT OR IGNORE 避免重复
    5. 重建被更新彩种的号码统计

    Args:
        force: True=强制所有彩种下载TXT逐行校验（手动更新用）
               False=仅检测到缺失或断层时才下载（自动更新用）

    Returns:
        dict: {"total_added": int, "updates": {lottery_code: added_count}}
    """
    raw_data = fetch_json_api()
    if not raw_data:
        print("[补数据] API 不可用，跳过补数据")
        return {"total_added": 0, "updates": {}}

    conn = get_connection()
    cursor = conn.cursor()
    result = {"total_added": 0, "updates": {}}
    updated_codes = []

    # 获取所有活跃彩种的 data_url
    cursor.execute("SELECT code, data_url FROM lottery_types WHERE active=1")
    lottery_urls = {row["code"]: row["data_url"] for row in cursor.fetchall()}

    for json_lotid, api_data in raw_data.items():
        db_code = JSON_LOTID_MAP.get(json_lotid)
        if not db_code or db_code not in lottery_urls:
            continue

        api_issue = api_data.get("issue", "")
        if not api_issue:
            continue

        # 查数据库最新记录
        cursor.execute(
            "SELECT draw_number, draw_date FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC LIMIT 1",
            (db_code,)
        )
        last_row = cursor.fetchone()
        if last_row and not force:
            # 非强制模式下：如果 API 返回的最新期号已经存在
            if str(api_issue) == last_row["draw_number"]:
                # 还需检查期号是否存在断层（中间少了期）
                if not _check_sequence_gap(cursor, db_code):
                    continue  # 无断层 → 数据完整，跳过
                else:
                    print(f"[补数据] {db_code}: 检测到期号断层，下载 TXT 文件补齐")
        elif last_row and force:
            # 强制模式下：无论最新期号是否一致，都下载 TXT 逐行校验
            print(f"[补数据] {db_code}: 强制全量校验，下载 TXT 文件")
        else:
            # 数据库无该彩种数据 → 需要全量导入
            pass

        data_url = lottery_urls[db_code]
        print(f"[补数据] {db_code}: 检测到缺失，下载 TXT 文件 {data_url}")

        lines = fetch_data(data_url)
        if not lines:
            print(f"  [补数据] {db_code}: TXT 下载为空，跳过")
            continue

        added = 0
        for line in lines:
            fields = line.split()
            if len(fields) < 3:
                continue
            draw_number = fields[0]
            draw_date = fields[1]

            # 检查是否已存在
            cursor.execute(
                "SELECT id FROM lottery_draws WHERE lottery_code=? AND draw_number=?",
                (db_code, draw_number)
            )
            if cursor.fetchone():
                continue  # 已存在，跳过

            parsed = parse_line(db_code, fields)
            if not parsed:
                continue

            cursor.execute("""
                INSERT OR IGNORE INTO lottery_draws
                (lottery_code, draw_number, draw_date, numbers, trial_numbers, machine_ball, draw_order, sale_amount, prize_pool, prizes, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                db_code,
                draw_number,
                draw_date,
                json.dumps(parsed.get("numbers", [])),
                json.dumps(parsed.get("trial_numbers")) if parsed.get("trial_numbers") else None,
                json.dumps(parsed.get("machine_ball")) if parsed.get("machine_ball") else None,
                json.dumps(parsed.get("draw_order")) if parsed.get("draw_order") else None,
                _safe_int(parsed.get("sale_amount"), 0),
                _safe_int(parsed.get("prize_pool"), 0) if parsed.get("prize_pool") is not None else None,
                json.dumps(parsed.get("prizes", [])),
                json.dumps(parsed.get("extra")) if parsed.get("extra") else None,
            ))

            if cursor.rowcount > 0:
                added += 1

        if added > 0:
            result["total_added"] += added
            result["updates"][db_code] = result["updates"].get(db_code, 0) + added
            updated_codes.append(db_code)
            print(f"  [补数据] {db_code}: 补齐 {added} 条记录")

    if result["total_added"] > 0:
        for code, count in result["updates"].items():
            cursor.execute("""
                INSERT INTO update_log (lottery_code, status, records_added, message, operator)
                VALUES (?, 'catchup', ?, ?, 'auto_updater')
            """, (code, count, f"断服补数据，新增{count}条"))
        conn.commit()

        # 重建受影响彩种的号码统计
        for code in set(updated_codes):
            try:
                stats = build_number_stats(code)
                print(f"  [统计] {code}: {stats['direct_count']} 直选号码")
                logger.info(f"[统计] {code}: {stats['direct_count']} 直选号码")
            except Exception as e:
                print(f"  [统计失败] {code}: {e}")
                logger.error(f"[统计失败] {code}: {e}")

    conn.close()

    if result["total_added"] > 0:
        print(f"[补数据完成] 共新增 {result['total_added']} 条记录")
    else:
        print("[补数据] 所有彩种数据已完整，无需补充")

    return result


async def smart_update_loop(check_interval=600):
    """智能更新循环：严格按开奖时间窗口执行

    核心逻辑：
    1. 仅在 21:00~活动窗口内进行轮训（不再以22:00为硬性截止）
    2. 调用 do_json_update() 一次性拉取所有彩种最新数据
    3. 条件满足时才执行更新（由 should_check_update 控制）
    4. 所有今日开奖彩种更新完毕 → 立即停止
    5. 安全限制：最晚不超过 23:00（防止异常情况无限循环）
    6. 跨天自动重置

    Args:
        check_interval: 轮询间隔（秒），默认600秒（10分钟）
    """
    import asyncio
    from app.draw_schedule import SCHEDULE, POLL_START_HOUR

    SAFETY_END_HOUR = 23  # 安全限制：最晚不超过 23:00

    # ─── 启动时先执行一次断服补数据 ───
    print("[自动更新] 启动时执行断服数据补齐检查...")
    logger.info("[自动更新] 启动时执行断服数据补齐检查")
    try:
        catch_up_result = catch_up_missing()
        if catch_up_result["total_added"] > 0:
            print(f"[自动更新] 启动补数据完成，新增 {catch_up_result['total_added']} 条")
            logger.info(f"[自动更新] 启动补数据完成，新增 {catch_up_result['total_added']} 条")
        else:
            print("[自动更新] 数据已完整，无需补充")
            logger.info("[自动更新] 数据已完整，无需补充")
    except Exception as e:
        print(f"[自动更新] 启动补数据出错: {e}")
        logger.error(f"[自动更新] 启动补数据出错: {e}")
        import traceback
        traceback.print_exc()

    while True:
        now = datetime.now()

        # ─── 非活动窗口：休眠到下一个 21:00 ───
        if now.hour < POLL_START_HOUR or now.hour >= SAFETY_END_HOUR:
            if now.hour < POLL_START_HOUR:
                # 今日尚未到活动窗口 → 等待今日的 POLL_START_HOUR
                next_start = datetime.combine(now.date(), time(POLL_START_HOUR, 0))
            else:
                # 已过安全终止时间 → 等待明天 POLL_START_HOUR
                next_day = now.date() + timedelta(days=1)
                next_start = datetime.combine(next_day, time(POLL_START_HOUR, 0))
            sleep_seconds = (next_start - now).total_seconds()
            print(
                f"[自动更新] 当前不在活动窗口 (起始 {POLL_START_HOUR}:00)，"
                f"休眠 {sleep_seconds/3600:.1f} 小时至 {next_start.strftime('%Y-%m-%d %H:%M')}"
            )
            log_polling("非活动窗口", f"休眠 {sleep_seconds/3600:.1f} 小时至 {next_start.strftime('%Y-%m-%d %H:%M')}")
            await asyncio.sleep(sleep_seconds)
            continue

        # ─── 进入活动窗口 ───
        today_str = date.today().strftime("%Y-%m-%d")
        today_draw_codes = [
            c for c in SCHEDULE
            if now.weekday() in SCHEDULE[c]["days"]
        ]
        updated_today = {}  # {lottery_code: "YYYY-MM-DD"}
        print(f"[自动更新] 进入活动窗口 {today_str} {POLL_START_HOUR}:00，"
              f"今日开奖彩种: {', '.join(today_draw_codes) if today_draw_codes else '无'}")
        log_polling("进入活动窗口",
            f"今日开奖: {', '.join(today_draw_codes) if today_draw_codes else '无'}")

        # 今日无开奖彩种 → 不必启动轮训
        if not today_draw_codes:
            print(f"[自动更新] 今日无开奖彩种，跳过轮训")
            log_polling("跳过轮训", "今日无开奖彩种")
            # 休眠到安全时间之后
            next_safe = datetime.combine(date.today(), time(SAFETY_END_HOUR, 0))
            sleep_sec = (next_safe - datetime.now()).total_seconds()
            if sleep_sec > 0:
                await asyncio.sleep(sleep_sec)
            continue

        while True:
            now = datetime.now()

            # 安全终止条件：23:00 已过（防止异常无限循环）
            if now.hour >= SAFETY_END_HOUR:
                print(f"[自动更新] 安全限制 {SAFETY_END_HOUR}:00 已过，今日轮训结束")
                break

            # 检查哪些彩种今日需更新但尚未更新
            pending_codes = []
            for code in today_draw_codes:
                if should_check_update(code, updated_today.get(code)):
                    pending_codes.append(code)

            # 终止条件：今日无待更新彩种
            if not pending_codes:
                remaining = [c for c in today_draw_codes if updated_today.get(c) != today_str]
                if not remaining:
                    print(f"[自动更新] 今日所有开奖彩种已全部更新完成，轮训结束")
                    log_polling("轮训结束", "今日所有开奖彩种已全部更新")
                else:
                    # 还有彩种没到开奖时间（开奖时间+8分钟还没到）
                    r_names = ", ".join(remaining)
                    print(f"[自动更新] 部分彩种尚未开奖: {r_names}，等待 {check_interval} 秒后重试")
                    await asyncio.sleep(check_interval)
                    continue
                break

            # ─── 有待更新彩种 → 执行一次 JSON 更新 ───
            codes_str = ", ".join(pending_codes)
            print(f"[自动更新] 待更新彩种: {codes_str}，开始获取数据...")
            log_polling("执行更新", f"待更新: {codes_str}")
            try:
                result = do_json_update()
                if result["total_added"] > 0:
                    # 标记所有有新增数据的彩种
                    for updated_code in result.get("updates", {}):
                        updated_today[updated_code] = today_str
                    code_summary = ", ".join(
                        f"{k}+{v}" for k, v in result["updates"].items()
                    )
                    print(f"[自动更新] 新增 {result['total_added']} 条 ({code_summary})")
                    log_polling("数据更新", f"{code_summary}")

                    # ★ 新增：新数据写入后，检查期号连续性，有断层则补齐
                    print("[自动更新] 检查期号连续性...")
                    try:
                        catch_up_missing()
                    except Exception as gap_e:
                        print(f"[自动更新] 连续性检查出错: {gap_e}")
                    
                    # 检查是否所有今日开奖彩种都已更新
                    all_done = all(
                        updated_today.get(c) == today_str
                        for c in today_draw_codes
                    )
                    if all_done:
                        print(f"[自动更新] 今日所有开奖彩种已全部更新完成，轮训结束")
                        break
                else:
                    print(f"[自动更新] 暂无新数据，等待 {check_interval} 秒后重试")
            except Exception as e:
                print(f"[自动更新] 出错: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(check_interval)
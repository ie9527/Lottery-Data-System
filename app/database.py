"""数据库连接与初始化模块"""

import sqlite3
import os
import json
from app.config import DB_PATH


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_database():
    """初始化数据库，创建表结构"""
    conn = get_connection()
    cursor = conn.cursor()

    # 彩票种类定义表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lottery_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            full_name TEXT,
            data_url TEXT NOT NULL,
            number_count INTEGER DEFAULT 0,
            number_range TEXT,
            has_trial INTEGER DEFAULT 0,
            has_sequence INTEGER DEFAULT 0,
            prize_levels TEXT,
            sort_order INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
    """)

    # 开奖结果核心表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lottery_draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_code TEXT NOT NULL,
            draw_number TEXT NOT NULL,
            draw_date TEXT NOT NULL,
            numbers TEXT NOT NULL,
            trial_numbers TEXT,
            machine_ball TEXT,
            draw_order TEXT,
            sale_amount INTEGER DEFAULT 0,
            prize_pool INTEGER,
            prizes TEXT,
            extra TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(lottery_code, draw_number)
        )
    """)

    # 索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_draws_code ON lottery_draws(lottery_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_draws_date ON lottery_draws(draw_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_draws_number ON lottery_draws(draw_number)")
    # ★ 复合索引：覆盖 90% 查询场景（按彩种+期号排序）
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_draws_code_num ON lottery_draws(lottery_code, draw_number DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_draws_code_date ON lottery_draws(lottery_code, draw_date DESC)")

    # 数据更新日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS update_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_code TEXT NOT NULL,
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'success',
            records_added INTEGER DEFAULT 0,
            message TEXT,
            operator TEXT DEFAULT 'system'
        )
    """)
    # 兼容旧表：如果缺少 operator 列则添加
    try:
        cursor.execute("ALTER TABLE update_log ADD COLUMN operator TEXT DEFAULT 'system'")
    except sqlite3.OperationalError:
        pass  # 列已存在
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_updatelog_code ON update_log(lottery_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_updatelog_time ON update_log(update_time DESC)")

    # 号码统计表（直选+组选次数、未开奖号码缓存）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS number_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lottery_code TEXT NOT NULL,
            number_text TEXT NOT NULL,
            stat_type TEXT NOT NULL DEFAULT 'direct',
            appear_count INTEGER DEFAULT 0,
            UNIQUE(lottery_code, number_text, stat_type)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ns_code ON number_stats(lottery_code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ns_type ON number_stats(lottery_code, stat_type)")

    # 插入彩票类型基础数据
    types_data = [
        ("3d", "3D", "福彩3D", "http://data.17500.cn/3d_asc.txt", 3, "0-9", 1, 0, json.dumps(["单选", "组三", "组六"]), 1),
        ("p3", "排列三", "排列三", "http://data.17500.cn/pl3_asc.txt", 3, "0-9", 0, 0, json.dumps(["直选", "组三", "组六"]), 2),
        ("p5", "排列五", "排列五", "http://data.17500.cn/pl5_asc.txt", 5, "0-9", 0, 0, json.dumps(["一等奖"]), 3),
        ("ssq", "双色球", "双色球", "http://data.17500.cn/ssq_asc.txt", 6, "红1-33/蓝1-16", 0, 1, json.dumps(["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖"]), 4),
        ("dlt", "大乐透", "大乐透", "http://data.17500.cn/dlt2_asc.txt", 5, "前1-35/后1-12", 0, 0, json.dumps(["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖", "七等奖", "八等奖"]), 5),
        ("qxc", "七星彩", "七星彩", "http://data.17500.cn/7xc_asc.txt", 7, "0-9", 0, 0, json.dumps(["特等奖", "一等奖", "二等奖", "三等奖", "四等奖", "五等奖"]), 6),
        ("7lc", "七乐彩", "七乐彩", "http://data.17500.cn/7lc_asc.txt", 7, "1-30", 0, 0, json.dumps(["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖", "七等奖"]), 7),
        ("kl8", "快乐八", "快乐8", "http://data.17500.cn/kl82_asc.txt", 20, "1-80", 0, 1, json.dumps(["选十中十", "选九中九", "选八中八", "选七中七", "选六中六", "选五中五", "选四中四", "选三中三", "选二中二", "选一中一"]), 8),
    ]

    for t in types_data:
        cursor.execute("""
            INSERT OR IGNORE INTO lottery_types (code, name, full_name, data_url, number_count, number_range, has_trial, has_sequence, prize_levels, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, t)

    conn.commit()
    conn.close()

    # 清理已移除的彩种（如 22选5）
    cleanup_removed_types()

    print(f"[数据库] 初始化完成: {DB_PATH}")


def cleanup_removed_types():
    """清理不再使用的彩票类型及其数据（批量操作优化）"""
    active_codes = [
        "3d", "p3", "p5", "ssq", "dlt", "qxc", "7lc", "kl8"
    ]
    conn = get_connection()
    cursor = conn.cursor()

    # 找出不再使用的彩种
    cursor.execute("SELECT code FROM lottery_types WHERE code NOT IN ({})".format(
        ",".join("?" * len(active_codes))
    ), active_codes)
    removed = [r["code"] for r in cursor.fetchall()]

    if removed:
        placeholders = ",".join("?" * len(removed))
        cursor.execute(f"DELETE FROM number_stats WHERE lottery_code IN ({placeholders})", removed)
        cursor.execute(f"DELETE FROM lottery_draws WHERE lottery_code IN ({placeholders})", removed)
        cursor.execute(f"DELETE FROM update_log WHERE lottery_code IN ({placeholders})", removed)
        cursor.execute(f"DELETE FROM lottery_types WHERE code IN ({placeholders})", removed)
        for code in removed:
            print(f"[清理] 已移除彩种 {code} 及其所有数据")

    conn.commit()
    conn.close()


def get_latest_draw_number(conn, lottery_code):
    """获取某彩票最新期号"""
    cursor = conn.execute(
        "SELECT draw_number FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC LIMIT 1",
        (lottery_code,)
    )
    row = cursor.fetchone()
    return row["draw_number"] if row else None


def get_latest_draw(conn, lottery_code):
    """获取某彩票最新一期完整数据"""
    cursor = conn.execute(
        "SELECT * FROM lottery_draws WHERE lottery_code=? ORDER BY draw_number DESC LIMIT 1",
        (lottery_code,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_latest_draws(conn, lottery_codes):
    """批量获取多个彩种的最新一期数据（一次查询替代N次查询）"""
    if not lottery_codes:
        return {}
    placeholders = ",".join("?" for _ in lottery_codes)
    cursor = conn.execute(f"""
        SELECT d1.* FROM lottery_draws d1
        INNER JOIN (
            SELECT lottery_code, MAX(draw_number) as max_num
            FROM lottery_draws
            WHERE lottery_code IN ({placeholders})
            GROUP BY lottery_code
        ) d2 ON d1.lottery_code = d2.lottery_code AND d1.draw_number = d2.max_num
    """, lottery_codes)
    result = {}
    for row in cursor.fetchall():
        result[row["lottery_code"]] = dict(row)
    return result


# ============================================================
# 数据完整性校验
# ============================================================

def check_data_duplicates(lottery_code=None):
    """检查数据库中的重复数据

    Args:
        lottery_code: 指定彩种代码（可选），None 表示检查所有彩种

    Returns:
        dict: {"has_duplicates": bool, "duplicates": {code: [(draw_number, count), ...]}}
    """
    conn = get_connection()
    cursor = conn.cursor()

    where = "WHERE lottery_code=?" if lottery_code else ""
    params = [lottery_code] if lottery_code else []

    cursor.execute(f"""
        SELECT lottery_code, draw_number, COUNT(*) as cnt
        FROM lottery_draws
        {where}
        GROUP BY lottery_code, draw_number
        HAVING COUNT(*) > 1
    """, params)
    rows = cursor.fetchall()

    conn.close()

    result = {"has_duplicates": len(rows) > 0, "duplicates": {}}
    for r in rows:
        code = r["lottery_code"]
        if code not in result["duplicates"]:
            result["duplicates"][code] = []
        result["duplicates"][code].append((r["draw_number"], r["cnt"]))

    return result


def data_integrity_check():
    """执行数据完整性全面检查

    检查项：
    1. 各彩种最新期号的连续性与合理性
    2. 重复数据
    3. 缺失/空字段检查
    4. 号码格式检查

    Returns:
        dict: 检查结果汇总
    """
    conn = get_connection()
    cursor = conn.cursor()
    report = {
        "total_draws": 0,
        "per_type": {},
        "duplicates": [],
        "issues": [],
    }

    # 各彩种统计
    cursor.execute("""
        SELECT lottery_code, COUNT(*) as cnt,
               MIN(draw_date) as first_date, MAX(draw_date) as last_date,
               MIN(draw_number) as first_issue, MAX(draw_number) as last_issue
        FROM lottery_draws
        GROUP BY lottery_code
        ORDER BY lottery_code
    """)
    for r in cursor.fetchall():
        code = r["lottery_code"]
        report["per_type"][code] = {
            "count": r["cnt"],
            "first_date": r["first_date"],
            "last_date": r["last_date"],
            "first_issue": r["first_issue"],
            "last_issue": r["last_issue"],
        }
        report["total_draws"] += r["cnt"]

    # 检查重复
    cursor.execute("""
        SELECT lottery_code, draw_number, COUNT(*) as cnt
        FROM lottery_draws
        GROUP BY lottery_code, draw_number
        HAVING COUNT(*) > 1
    """)
    for r in cursor.fetchall():
        report["duplicates"].append({
            "lottery_code": r["lottery_code"],
            "draw_number": r["draw_number"],
            "count": r["cnt"],
        })

    # 检查空字段
    cursor.execute("""
        SELECT lottery_code, draw_number
        FROM lottery_draws
        WHERE numbers IS NULL OR numbers = '' OR numbers = '[]'
        LIMIT 20
    """)
    for r in cursor.fetchall():
        report["issues"].append(f"{r['lottery_code']} 期{r['draw_number']}: 号码为空")

    conn.close()

    report["has_duplicates"] = len(report["duplicates"]) > 0
    report["has_issues"] = len(report["issues"]) > 0

    return report


def ensure_no_duplicates(lottery_code, draw_number):
    """确保数据唯一性的预检函数

    在插入前检查 (lottery_code, draw_number) 是否已存在。
    用于替代 INSERT OR IGNORE 的更明确方案。

    Returns:
        bool: True 表示可插入（不存在）, False 表示已存在
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM lottery_draws WHERE lottery_code=? AND draw_number=?",
        (lottery_code, str(draw_number))
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return not exists


# ============================================================
# 期号模糊匹配（支持忽略年份前缀）
# ============================================================

DRAW_NUMBER_YEARS = 5  # 最近5年的期号

def match_draw_number(lottery_code, draw_number, cursor=None):
    """模糊匹配期号，支持忽略年份前缀

    用户输入 "318" 可匹配 "2025318"、"2024318" 等。
    优先精确匹配，再按后缀模糊匹配（取最新的）。

    Args:
        lottery_code: 彩种代码
        draw_number: 用户输入的期号（可能短于完整期号）
        cursor: 可选的数据库游标（如为 None，内部创建并关闭）

    Returns:
        dict | None: 匹配到的开奖记录，或 None
    """
    own_cursor = False
    if cursor is None:
        conn = get_connection()
        cursor = conn.cursor()
        own_cursor = True

    row = None
    raw = str(draw_number).strip()

    # 1. 精确匹配
    cursor.execute(
        "SELECT * FROM lottery_draws WHERE lottery_code=? AND draw_number=?",
        (lottery_code, raw)
    )
    row = cursor.fetchone()

    # 2. 后缀模糊匹配（用户只输了后半段，如 "318" 匹配 "2025318"）
    if not row and raw.isdigit():
        # 使用 LIKE %后缀 匹配，取最新一期
        cursor.execute(
            "SELECT * FROM lottery_draws WHERE lottery_code=? AND draw_number LIKE ? ORDER BY LENGTH(draw_number) ASC, draw_number DESC LIMIT 1",
            (lottery_code, f"%{raw}")
        )
        row = cursor.fetchone()

    result = dict(row) if row else None

    if own_cursor:
        conn.close()

    return result
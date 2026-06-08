"""启动脚本 - 先构建号码统计，再启动服务器"""

import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(__file__))

from app.database import get_connection, init_database
from app.stats_builder import build_number_stats
from app.auto_updater import catch_up_missing

if __name__ == "__main__":
    import uvicorn

    # 1. 先初始化数据库
    init_database()

    # 2. 检查号码统计是否需要构建或重建
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM number_stats")
    stats_count = cursor.fetchone()["cnt"]

    # 检测旧版格式：3D号码应该为3位（如"073"），旧版为6位（如"000703"）
    need_rebuild = False
    if stats_count > 0:
        cursor.execute("SELECT number_text FROM number_stats WHERE lottery_code='3d' AND stat_type='direct' LIMIT 1")
        row = cursor.fetchone()
        if row and len(row["number_text"]) != 3:
            need_rebuild = True
            print(f"[启动] 检测到旧版号码格式（{row['number_text']}），需要重建统计...")

    conn.close()

    if stats_count == 0 or need_rebuild:
        if need_rebuild:
            # 清空旧数据
            conn2 = get_connection()
            conn2.execute("DELETE FROM number_stats")
            conn2.commit()
            conn2.close()
            print("[启动] 旧版统计数据已清除")
        else:
            print("[启动] 首次运行，正在构建号码统计（约需10-20秒）...")

        types_codes = ["3d", "p3", "p5", "ssq", "dlt", "qxc", "7lc", "kl8"]
        for code in types_codes:
            try:
                result = build_number_stats(code)
                print(f"  [OK] {code}: {result['direct_count']} 个直选号码统计完成")
            except Exception as e:
                print(f"  [ERR] {code} 统计失败: {e}")
        print("[启动] 所有号码统计构建完成！")
    else:
        print(f"[启动] 号码统计已存在（{stats_count} 条记录），跳过构建")

    # 3. 执行断服补数据检查（服务器离线期间遗漏的开奖数据）
    print("[启动] 执行断服数据补齐检查...")
    try:
        catch_up_result = catch_up_missing()
        if catch_up_result["total_added"] > 0:
            print(f"[启动] 补数据完成，新增 {catch_up_result['total_added']} 条记录")
        else:
            print("[启动] 数据已完整，无需补充")
    except Exception as e:
        print(f"[启动] 补数据出错: {e}")
        import traceback
        traceback.print_exc()

    # 4. 启动 Web 服务器
    print("[启动] 启动 Web 服务器...")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=["./app", "./templates"],
    )
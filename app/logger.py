"""日志系统模块 - 按日期轮转的日志文件

使用方式：
    from app.logger import logger
    logger.info("消息")
    logger.error("错误信息", exc_info=True)
    logger.debug("调试信息")
"""

import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# 日志目录
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# 日志文件路径（按日期轮转，保留30天）
LOG_FILE = os.path.join(LOGS_DIR, "system.log")

def setup_logger():
    """配置日志系统

    输出目标：
    1. 日志文件（按天轮转，保留30天）
    2. 控制台（标准输出）

    日志级别：
    - DEBUG: 详细调试信息
    - INFO: 常规操作信息
    - WARNING: 警告
    - ERROR: 错误
    - CRITICAL: 严重错误
    """
    logger = logging.getLogger("lottery_system")
    logger.setLevel(logging.DEBUG)

    # 防止重复添加 handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件 handler（按天轮转，保留30天）
    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


def log_update(lottery_code, records_added, status="success", message=None):
    """记录数据更新操作到日志文件

    Args:
        lottery_code: 彩种代码
        records_added: 新增记录数
        status: success / catchup / error
        message: 附加消息
    """
    msg = message or f"[{lottery_code}] 新增 {records_added} 条记录"
    if status == "error":
        logger.error(msg)
    elif status == "catchup":
        logger.warning(msg)
    else:
        logger.info(msg)


def log_polling(action, detail=None):
    """记录轮训操作

    Args:
        action: 轮训动作描述（如 "开始轮训"、"执行更新"、"休眠等待"）
        detail: 附加详情
    """
    msg = f"[轮训] {action}"
    if detail:
        msg += f" - {detail}"
    logger.info(msg)
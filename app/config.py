"""统一配置文件 - 集中管理所有可配置参数"""

import os
from dotenv import load_dotenv

# 加载 .env 文件（支持从项目根目录加载）
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print(f"[config] .env not found at: {dotenv_path}")

# ============================================================
# 服务器配置
# ============================================================
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8001

# ============================================================
# 数据库配置
# ============================================================
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_FILENAME = "lottery.db"
DB_PATH = os.path.join(DB_DIR, DB_FILENAME)

# ============================================================
# 数据抓取配置
# ============================================================
# JSON API 地址
JSON_API_URL = "https://www.17500.cn/inx/awards.html"
# TXT 数据抓取超时（秒）
FETCH_TIMEOUT = 30
# JSON API 抓取超时（秒）
JSON_API_TIMEOUT = 15
# 请求头 User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ============================================================
# 自动更新配置
# ============================================================
# 智能更新轮询间隔（秒）
POLL_INTERVAL = 600  # 10 分钟
# 开奖时间窗口 - 起始（21:00 前禁止读取）
POLL_START_HOUR = 21
# 开奖时间窗口 - 安全终止（最晚不超过此时间）
POLL_END_HOUR = 23
# 开奖后等待延迟（分钟，直播结束等待时间）
POST_DRAW_DELAY = 8

# ============================================================
# 手动更新配置
# ============================================================
# 手动更新冷却时间（秒）
MANUAL_UPDATE_COOLDOWN = 3600  # 1 小时

# ============================================================
# 缓存配置
# ============================================================
# 默认缓存 TTL（秒）
CACHE_DEFAULT_TTL = 60
# 倒计时缓存 TTL（秒）
CACHE_COUNTDOWN_TTL = 30
# 系统统计缓存 TTL（秒）
CACHE_SYSTEM_STATS_TTL = 300
# 系统状态缓存 TTL（秒）
CACHE_SYSTEM_STATUS_TTL = 10
# 号码排行缓存 TTL（秒）
CACHE_RANKING_TTL = 120

# ============================================================
# 开奖时间配置（核心配置 - 倒计时与更新均依赖于此）
# day: Python weekday() → 0=周一, 1=周二, ..., 6=周日
# ============================================================
DRAW_SCHEDULE = {
    "3d": {
        "name": "福彩3D",
        "days": [0, 1, 2, 3, 4, 5, 6],  # 每天
        "time": "21:15",
        "interval": "每天",
    },
    "p3": {
        "name": "排列三",
        "days": [0, 1, 2, 3, 4, 5, 6],  # 每天
        "time": "21:25",
        "interval": "每天",
    },
    "p5": {
        "name": "排列五",
        "days": [0, 1, 2, 3, 4, 5, 6],  # 每天
        "time": "21:25",
        "interval": "每天",
    },
    "ssq": {
        "name": "双色球",
        "days": [1, 3],  # 周二=1 周四=3
        "time": "21:15",
        "interval": "二/四",
    },
    "dlt": {
        "name": "大乐透",
        "days": [0, 2, 5],  # 周一=0 周三=2 周六=5
        "time": "21:25",
        "interval": "一/三/六",
    },
    "kl8": {
        "name": "快乐8",
        "days": [0, 1, 2, 3, 4, 5, 6],  # 每天
        "time": "21:30",
        "interval": "每天",
    },
    "7lc": {
        "name": "七乐彩",
        "days": [0, 2, 4],  # 周一=0 周三=2 周五=4
        "time": "21:15",
        "interval": "一/三/五",
    },
    "qxc": {
        "name": "七星彩",
        "days": [1, 4],  # 周二=1 周五=4
        "time": "21:25",
        "interval": "二/五",
    },
}

# 彩种代码与名称映射（自动从 SCHEDULE 生成）
LOTTERY_NAMES = {k: v["name"] for k, v in DRAW_SCHEDULE.items()}

# ============================================================
# 号码搜索配置
# ============================================================
# 分页大小
SEARCH_PAGE_SIZE = 30
STATS_PAGE_SIZE = 100
UNUSED_PAGE_SIZE = 200
DRAW_PAGE_SIZE = 50

# ============================================================
# AI 对话配置
# ============================================================
# DeepSeek API 配置（支持环境变量覆盖）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("[config] ⚠️ DEEPSEEK_API_KEY 未配置")
else:
    print(f"[config] ✅ DEEPSEEK_API_KEY 已配置 ({DEEPSEEK_API_KEY[:12]}...)")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_USE_BETA = os.environ.get("DEEPSEEK_USE_BETA", "True").strip().lower() in ("true", "1", "yes")
DEEPSEEK_THINKING_ENABLED = os.environ.get("DEEPSEEK_THINKING_ENABLED", "True").strip().lower() in ("true", "1", "yes")
DEEPSEEK_REASONING_EFFORT = os.environ.get("DEEPSEEK_REASONING_EFFORT", "high")

# 对话限制
CHAT_MAX_HISTORY = 20                          # 最大历史轮次
CHAT_MAX_TOKENS = 8192                         # 单次最大输出 tokens（复杂分析需要更大输出）
CHAT_TIMEOUT_SECONDS = 60                      # API 超时时间（复杂查询可能更久）
CHAT_TOOL_CALLS_LIMIT = 20                     # 单次对话最多工具调用次数
CHAT_RATE_LIMIT_PER_MIN = 10                   # 每分钟每用户最大请求数
CHAT_SESSION_TTL = 3600                        # 会话过期时间（1小时）

# ============================================================
# DeepSeek 定价标准（元/百万 tokens）
# ============================================================
# 参考: https://api-docs.deepseek.com/zh-cn/quick_start/pricing
DEEPSEEK_PRICE_CACHE_HIT = 0.02    # 缓存命中输入价格
DEEPSEEK_PRICE_CACHE_MISS = 1.0    # 缓存未命中输入价格
DEEPSEEK_PRICE_OUTPUT = 2.0        # 输出价格
"""数据抓取模块 - 从17500.cn下载彩票数据"""

import requests
import io
import json as json_module
from app.config import JSON_API_URL, FETCH_TIMEOUT, JSON_API_TIMEOUT, USER_AGENT

# 彩种代码映射：JSON API中的lotid → 系统数据库中的lottery_code
JSON_LOTID_MAP = {
    "3d": "3d",
    "pl3": "p3",
    "pl5": "p5",
    "ssq": "ssq",
    "dlt": "dlt",
    "kl8": "kl8",
    "7lc": "7lc",
    "7xc": "qxc",
}

# 互换映射（系统代码 → JSON lotid）
SYSTEM_TO_JSON = {v: k for k, v in JSON_LOTID_MAP.items()}


def fetch_data(url):
    """从指定URL下载彩票数据文本

    Args:
        url: 数据文件URL

    Returns:
        按行分割的文本列表，或空列表
    """
    try:
        # 设置超时和请求头
        headers = {
            "User-Agent": USER_AGENT,
        }
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)

        # 尝试检测编码
        content = resp.content
        # 先尝试GBK/GB2312 (中文网站常用)
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("gb18030", errors="replace")

        # 按行分割，过滤空行
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        print(f"[抓取] {url} → 共 {len(lines)} 行数据")
        return lines

    except Exception as e:
        print(f"[抓取失败] {url} → {e}")
        return []


def fetch_json_api(timeout=15):
    """从JSON接口获取所有彩种最新数据

    Returns:
        dict: {lottery_code: {...data...}} 或 None（失败）
    """
    url = JSON_API_URL
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=JSON_API_TIMEOUT)
        resp.encoding = "utf-8"
        data = resp.json()
        if data.get("status") != 1 or "data" not in data:
            print(f"[JSON抓取] 接口返回异常: {data}")
            return None
        print(f"[JSON抓取] 成功获取 {len(data['data'])} 个彩种最新数据")
        return data["data"]
    except Exception as e:
        print(f"[JSON抓取失败] {e}")
        return None
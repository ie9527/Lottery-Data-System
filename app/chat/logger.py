"""AI对话日志系统

记录用户与AI的完整对话、工具调用、数据库查询等日志，
以JSON格式按日期分文件存储。
"""

import json
import os
import time
from datetime import datetime
from typing import Optional


class ChatLogger:
    """对话日志记录器"""
    
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "chat")
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
    
    def _get_log_file(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"chat_{today}.jsonl")
    
    async def log_conversation(
        self,
        session_id: str,
        user_message: str,
        assistant_reply: str,
        tool_calls: list = None,
        tool_results: list = None,
        usage: dict = None,
        latency_ms: int = 0,
        status: str = "success",
        error: str = None,
    ):
        """记录一轮完整对话"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "user_message": user_message,
            "assistant_reply": assistant_reply,
            "tool_calls": tool_calls or [],
            "tool_results": tool_results or [],
            "usage": usage or {},
            "latency_ms": latency_ms,
            "status": status,
        }
        if error:
            record["error"] = error
        
        # 追加写入 JSONL 文件
        filepath = self._get_log_file()
        try:
            # 使用普通文件写入避免 async 复杂性
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志写入失败不影响主流程
    
    async def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        args: dict,
        result_summary: str,
        status: str = "success",
    ):
        """记录工具调用"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "type": "tool_call",
            "tool_name": tool_name,
            "args": args,
            "result_summary": result_summary[:200],
            "status": status,
        }
        filepath = self._get_log_file()
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


# 全局单例
_logger = None

def get_chat_logger() -> ChatLogger:
    global _logger
    if _logger is None:
        _logger = ChatLogger()
    return _logger
"""会话上下文管理

管理多个用户会话的历史消息、自动截断、过期清理。
"""

import uuid
import time
import asyncio
from datetime import datetime
from typing import Optional

from app import config


class ChatSession:
    """单个用户会话"""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.history: list[dict] = []  # [{"role": "user"/"assistant", "content": ...}]
        self.message_context: list[dict] = []  # 完整消息上下文（含 tool_calls）
        self.created_at = time.time()
        self.last_active = time.time()

    def add_message(self, role: str, content: str):
        """添加一条消息到历史"""
        self.history.append({"role": role, "content": content})
        self.last_active = time.time()
        # 自动截断：保留最近 N 轮
        max_msgs = config.CHAT_MAX_HISTORY * 2  # user + assistant
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]

    def save_message_context(self, context: list[dict]):
        """保存完整消息上下文（含 tool_calls），供下一轮对话使用
        
        自动截断过长的上下文内容，避免超出模型上下文窗口。
        """
        # 限制上下文长度：保留最近的 N 条消息
        max_msgs = config.CHAT_MAX_HISTORY * 4  # 比普通历史多，因为含 tool 消息
        if len(context) > max_msgs:
            # 保留系统消息 + 最近的 max_msgs-1 条
            context = context[-max_msgs + 1:]
        
        # 精简过长的 tool 结果内容（超过 2000 字符的截断）
        for msg in context:
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                if len(msg["content"]) > 2000:
                    msg["content"] = msg["content"][:2000] + "...[已截断]"
            # 安全过滤：剥离 reasoning_content（仅API输出，不可用于输入）
            if "reasoning_content" in msg:
                del msg["reasoning_content"]
        
        self.message_context = context
        self.last_active = time.time()

    def build_messages(self, system_prompt: str, user_message: str) -> list:
        """构建发送给 DeepSeek 的完整 messages

        格式：[system, (message_context | history)..., user]

        优先使用 message_context（完整上下文含 tool_calls），
        没有则回退到 history（简化的用户/助理消息对）。
        """
        messages = [{"role": "system", "content": system_prompt}]
        if self.message_context:
            messages.extend(self.message_context)
        else:
            messages.extend(self.history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def is_expired(self) -> bool:
        """判断会话是否过期"""
        return time.time() - self.last_active > config.CHAT_SESSION_TTL


# 全局会话存储（内存，开发阶段够用）
_sessions: dict[str, ChatSession] = {}


def get_or_create_session(session_id: Optional[str] = None) -> ChatSession:
    """获取或创建会话"""
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        # 检查是否过期
        if session.is_expired():
            del _sessions[session_id]
            session = ChatSession(session_id)
            _sessions[session_id] = session
        return session

    session = ChatSession(session_id)
    _sessions[session.session_id] = session
    return session


async def clean_expired_sessions():
    """后台任务：每小时清理过期会话"""
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        expired = [
            sid for sid, s in _sessions.items()
            if now - s.last_active > config.CHAT_SESSION_TTL
        ]
        for sid in expired:
            del _sessions[sid]
        if expired:
            from app.logger import logger
            logger.info(f"已清理 {len(expired)} 个过期会话")
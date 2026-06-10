"""DeepSeek API 客户端封装

封装 OpenAI SDK 调用 DeepSeek API，支持：
- 流式（SSE）和非流式调用
- 思考模式（reasoning_content）
- Tool Calls（解析和重入）
- KV Cache 命中统计捕获
- 错误处理和重试
- 余额查询
"""

import json
import time
from typing import AsyncGenerator, Optional

from openai import OpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from openai import APIError, APIConnectionError, RateLimitError, AuthenticationError

from app import config


class DeepSeekClient:
    """DeepSeek API 客户端"""

    def __init__(self):
        base_url = config.DEEPSEEK_BASE_URL
        if config.DEEPSEEK_USE_BETA:
            base_url = "https://api.deepseek.com/beta"

        self.base_url = base_url
        self.api_key = config.DEEPSEEK_API_KEY

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=base_url,
            timeout=config.CHAT_TIMEOUT_SECONDS,
        )
        self.model = config.DEEPSEEK_MODEL

    def _build_extra_body(self, session_id: str, thinking_enabled: bool = True) -> dict:
        """构建 extra_body 参数"""
        body = {}
        if thinking_enabled:
            body["thinking"] = {"type": "enabled"}
        if session_id:
            body["user_id"] = session_id
        return body

    async def get_balance(self) -> dict:
        """查询 DeepSeek 账号余额

        Returns:
            {
                "is_available": bool,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00"
                    }
                ]
            }
        """
        try:
            import httpx
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.deepseek.com/user/balance",
                    headers=headers,
                )
                if resp.status_code == 200:
                    return resp.json()
                else:
                    error_msg = self._map_http_error(resp.status_code, "余额查询")
                    return {"error": error_msg, "status_code": resp.status_code}
        except httpx.TimeoutException:
            return {"error": "余额查询超时，请稍后重试"}
        except Exception as e:
            return {"error": f"余额查询失败: {str(e)}"}

    def _map_http_error(self, status_code: int, context: str = "") -> str:
        """将 HTTP 状态码映射为用户友好的错误信息"""
        error_map = {
            400: "请求格式错误，请检查输入参数",
            401: "API Key 认证失败，请检查 API Key 是否正确",
            402: "账号余额不足，请前往 DeepSeek 平台充值",
            422: "请求参数错误，请检查输入参数",
            429: "请求过于频繁，请稍后重试",
            500: "DeepSeek 服务器内部故障，请稍后重试",
            503: "DeepSeek 服务器负载过高，请稍后重试",
        }
        msg = error_map.get(status_code, f"未知错误 (HTTP {status_code})")
        if context:
            msg = f"{context}失败: {msg}"
        return msg

    def _handle_api_error(self, error: Exception) -> str:
        """统一处理 API 调用中的异常，返回用户友好的错误信息"""
        if isinstance(error, AuthenticationError):
            return "API Key 认证失败，请检查 API Key 是否正确配置"
        elif isinstance(error, RateLimitError):
            return "请求过于频繁，已达到速率限制，请稍后重试"
        elif isinstance(error, APIConnectionError):
            return "无法连接到 DeepSeek API 服务器，请检查网络连接"
        elif isinstance(error, APIError):
            status = error.response.status_code if hasattr(error, 'response') and hasattr(error.response, 'status_code') else 0
            return self._map_http_error(status, "API 调用")
        else:
            return f"AI 服务异常: {str(error)}"

    async def chat_non_stream(
        self,
        messages: list,
        tools: Optional[list] = None,
        session_id: str = "",
        thinking_enabled: bool = True,
    ) -> dict:
        """非流式调用 DeepSeek API

        Returns:
            {
                "content": str,           # 回复内容
                "tool_calls": [...],       # 工具调用列表
                "reasoning_content": str,  # 思考内容（思考模式下）
                "usage": {...},           # token 用量
                "error": str,             # 错误信息（如有）
            }
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": config.CHAT_MAX_TOKENS,
            "extra_body": self._build_extra_body(session_id, thinking_enabled),
        }

        if thinking_enabled:
            kwargs["reasoning_effort"] = config.DEEPSEEK_REASONING_EFFORT

        if tools:
            kwargs["tools"] = tools

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            error_msg = self._handle_api_error(e)
            return {
                "content": "",
                "tool_calls": [],
                "reasoning_content": "",
                "usage": {},
                "latency_ms": 0,
                "error": error_msg,
            }

        choice = response.choices[0]
        msg = choice.message

        result = {
            "content": msg.content or "",
            "tool_calls": [],
            "reasoning_content": "",
            "usage": {},
            "latency_ms": 0,
            "error": "",
        }

        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        # 捕获思考内容
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            result["reasoning_content"] = msg.reasoning_content

        # 捕获 token 用量
        if response.usage:
            usage = response.usage
            result["usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "prompt_cache_hit_tokens": getattr(usage, "prompt_cache_hit_tokens", 0),
                "prompt_cache_miss_tokens": getattr(usage, "prompt_cache_miss_tokens", 0),
            }

        return result

    async def chat_stream(
        self,
        messages: list,
        tools: Optional[list] = None,
        session_id: str = "",
        thinking_enabled: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """流式调用 DeepSeek API（SSE）

        逐 chunk 产出：
            {"type": "text", "content": "..."}           # 普通文本
            {"type": "reasoning", "content": "..."}       # 思考内容
            {"type": "tool_calls", "content": [...]}       # 工具调用
            {"type": "usage", "content": {...}}            # token 用量
            {"type": "error", "content": "..."}            # 错误信息
            {"type": "done"}                               # 完成
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": config.CHAT_MAX_TOKENS,
            "extra_body": self._build_extra_body(session_id, thinking_enabled),
        }

        if thinking_enabled:
            kwargs["reasoning_effort"] = config.DEEPSEEK_REASONING_EFFORT

        if tools:
            kwargs["tools"] = tools

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            error_msg = self._handle_api_error(e)
            yield {"type": "error", "content": error_msg}
            yield {"type": "done"}
            return

        tool_calls_buffer = {}
        reasoning_buffer = ""
        usage = {}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # 思考内容
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_buffer += delta.reasoning_content
                yield {"type": "reasoning", "content": delta.reasoning_content}

            # 普通文本
            if delta.content:
                yield {"type": "text", "content": delta.content}

            # 工具调用（流式累加）
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id or "",
                            "type": tc.type or "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["function"]["arguments"] += tc.function.arguments

            # usage 信息（最后一个 chunk 携带）
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                    "total_tokens": chunk.usage.total_tokens,
                    "prompt_cache_hit_tokens": getattr(chunk.usage, "prompt_cache_hit_tokens", 0),
                    "prompt_cache_miss_tokens": getattr(chunk.usage, "prompt_cache_miss_tokens", 0),
                }

        # 发送工具调用结果
        if tool_calls_buffer:
            sorted_calls = [tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())]
            yield {"type": "tool_calls", "content": sorted_calls}

        # 发送 usage
        if usage:
            yield {"type": "usage", "content": usage}

        yield {"type": "done"}
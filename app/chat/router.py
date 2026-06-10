"""AI 对话路由

- POST /api/chat   → 非流式对话接口
- POST /api/chat/stream → 流式对话接口（SSE）
- GET  /api/chat/balance → 查询 DeepSeek 余额
- GET  /chat       → 聊天页面
"""

import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from app.chat.agent import ChatAgent
from app.chat.context import get_or_create_session
from app.chat.deepseek import DeepSeekClient
from app.chat.logger import get_chat_logger
from app.chat.prompts import should_enable_thinking
from app import config


# ============================================================
# 数据模型
# ============================================================

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息")
    session_id: str = Field("", description="会话ID（可选，不传则服务端生成）")
    thinking: bool = Field(True, description="是否启用深度思考（默认启用）")


class ChatResponse(BaseModel):
    status: str = "success"
    data: dict


# ============================================================
# API 路由
# ============================================================

router = APIRouter()

# 记录每个会话是否为首次对话
_first_message_sessions = set()


@router.post("/chat")
async def chat(req: ChatRequest):
    """非流式对话接口"""
    if not config.DEEPSEEK_API_KEY:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "请先配置 DeepSeek API Key（设置环境变量 DEEPSEEK_API_KEY）"},
        )

    session = get_or_create_session(req.session_id)
    agent = ChatAgent()

    try:
        result = await agent.process(session, req.message)
    except Exception as e:
        await get_chat_logger().log_conversation(
            session_id=session.session_id,
            user_message=req.message,
            assistant_reply="",
            status="error",
            error=str(e),
        )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"AI 对话出错: {str(e)}"},
        )

    # 保存到会话历史
    session.add_message("user", req.message)
    session.add_message("assistant", result["reply"])

    # 记录日志
    await get_chat_logger().log_conversation(
        session_id=session.session_id,
        user_message=req.message,
        assistant_reply=result["reply"],
        tool_calls=result.get("tool_calls", []),
        usage=result.get("usage", {}),
        latency_ms=result["latency_ms"],
    )

    return {
        "status": "success",
        "data": {
            "reply": result["reply"],
            "session_id": session.session_id,
            "latency_ms": result["latency_ms"],
            "tool_calls": result["tool_calls"],
            "usage": result["usage"],
        },
    }


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, fastapi_request: Request):
    """流式对话接口（SSE）"""
    if not config.DEEPSEEK_API_KEY:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "请先配置 DeepSeek API Key"},
        )

    session = get_or_create_session(req.session_id)
    agent = ChatAgent()
    user_message = req.message
    stream_start = time.time()

    # 判断是否为该会话的首次对话
    session_id = session.session_id
    is_first = session_id not in _first_message_sessions
    _first_message_sessions.add(session_id)

    async def event_generator():
        full_reply = ""
        tool_calls_logged = []
        usage_logged = {}
        error_logged = None
        try:
            async for chunk in agent.process_stream(session, user_message, thinking=req.thinking):
                chunk["session_id"] = session.session_id
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

                if chunk.get("type") == "text":
                    full_reply += chunk["content"]
                elif chunk.get("type") == "tool_call":
                    tool_calls_logged.append(chunk.get("content", {}))
                elif chunk.get("type") == "usage":
                    usage_data = chunk.get("content", {})
                    # 首次对话时，系统提示词尚未被缓存，将缓存命中数据清零
                    if is_first and "prompt_cache_hit_tokens" in usage_data:
                        usage_data["prompt_cache_hit_tokens"] = 0
                    usage_logged = usage_data
                elif chunk.get("type") == "error":
                    error_logged = chunk.get("content", "")
                elif chunk.get("type") == "message_context":
                    # 保存完整上下文（含 tool_calls），供下一轮对话使用
                    session.save_message_context(chunk["content"])

            # 保存到会话历史
            session.add_message("user", user_message)
            if full_reply:
                session.add_message("assistant", full_reply)

            yield "data: [DONE]\n\n"

        except Exception as e:
            error_logged = str(e)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        # 记录日志（在流结束后执行，不阻塞响应）
        latency_ms = int((time.time() - stream_start) * 1000)
        await get_chat_logger().log_conversation(
            session_id=session.session_id,
            user_message=user_message,
            assistant_reply=full_reply,
            tool_calls=tool_calls_logged,
            usage=usage_logged,
            latency_ms=latency_ms,
            status="error" if error_logged else "success",
            error=error_logged,
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/balance")
async def chat_balance():
    """查询 DeepSeek 账号余额"""
    if not config.DEEPSEEK_API_KEY:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "请先配置 DeepSeek API Key"},
        )
    try:
        client = DeepSeekClient()
        balance = await client.get_balance()
        return {"status": "success", "data": balance}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"余额查询失败: {str(e)}"},
        )


# ============================================================
# 页面路由
# ============================================================

page_router = APIRouter()


@page_router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """聊天页面"""
    from app.routes_page import get_total_records, render

    return render("chat.html",
        page_title="AI 对话",
        page="chat",
        total_records=get_total_records(),
        api_key_configured=bool(config.DEEPSEEK_API_KEY),
        thinking_enabled=config.DEEPSEEK_THINKING_ENABLED,
    )
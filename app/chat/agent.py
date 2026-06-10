"""Agent 核心编排

流程：
用户消息 → 构建 messages（system + history + user）→ 调用 LLM
  ├─ 返回 content → 返回给用户（无工具调用）
  └─ 返回 tool_calls → 执行工具 → 结果注入 → 再次调用 LLM → 返回 content

流式模式下：
- 实时输出思考过程（reasoning_content）
- 实时展示工具调用状态
- 最终输出逐 token 流式呈现
"""

import json
import time
from typing import AsyncGenerator

from app import config
from app.chat.deepseek import DeepSeekClient
from app.chat.tools import TOOL_DEFINITIONS, execute_tool
from app.chat.prompts import SYSTEM_PROMPT
from app.chat.context import ChatSession


def format_tools_description() -> str:
    """生成工具描述文本，嵌入 system prompt"""
    lines = []
    for t in TOOL_DEFINITIONS:
        fn = t["function"]
        name = fn["name"]
        desc = fn["description"]
        params = fn["parameters"].get("properties", {})
        param_desc = ", ".join(
            f"{k}: {v.get('description', '')}" for k, v in params.items()
        )
        lines.append(f"- **{name}**：{desc}")
        if param_desc:
            lines.append(f"  参数：{param_desc}")
    return "\n".join(lines)


def _summarize_tool_result(name: str, result: dict) -> str:
    """对工具返回结果做摘要，避免前端显示大量原始数据"""
    if isinstance(result, list):
        if len(result) == 0:
            return "无数据"
        if len(result) <= 5:
            items = [str(r) if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in result]
            return f"共 {len(result)} 条: " + ", ".join(items)
        return f"共 {len(result)} 条结果"
    if isinstance(result, dict):
        # 提取关键字段
        summary_parts = []
        for key in ["total", "count", "direct_count", "group_count"]:
            if key in result and result[key] is not None:
                summary_parts.append(f"{key}={result[key]}")
        if summary_parts:
            return ", ".join(summary_parts)
        return str(result)[:100]
    return str(result)[:100]


class ChatAgent:
    """AI 对话 Agent

    KV Cache 优化策略：
    1. system prompt 在应用生命周期内保持不变 → 请求前缀固定，利于缓存
    2. 多轮对话通过 message_context 传递完整上下文 → 后续请求可复用前一轮前缀
    3. tool 结果内容截断至 2000 字符 → 减少 token 总量
    4. reasoning_content 字段从上下文中剥离 → 防止无效 token 占用缓存
    5. session_id 通过 extra_body 的 user_id 字段传递 → 辅助 DeepSeek 缓存分组
    6. 消息数量限制在 CHAT_MAX_HISTORY * 4 条 → 避免上下文过长导致缓存效率下降
    """

    def __init__(self):
        self.client = DeepSeekClient()
        self.tools = TOOL_DEFINITIONS
        self.system_prompt = SYSTEM_PROMPT.format(
            tools_description=format_tools_description()
        )

    async def process(
        self,
        session: ChatSession,
        user_message: str,
    ) -> dict:
        """处理单次对话（非流式）

        Returns:
            {
                "reply": str,
                "tool_calls": [...],
                "usage": {...},
                "latency_ms": int,
            }
        """
        start = time.time()
        messages = session.build_messages(self.system_prompt, user_message)
        all_tool_calls = []

        for _ in range(config.CHAT_TOOL_CALLS_LIMIT):
            result = await self.client.chat_non_stream(
                messages=messages,
                tools=self.tools,
                session_id=session.session_id,
            )

            if result["tool_calls"]:
                all_tool_calls.extend(result["tool_calls"])

                assistant_msg = {
                    "role": "assistant",
                    "content": result["content"] or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": tc["type"],
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in result["tool_calls"]
                    ],
                }
                messages.append(assistant_msg)

                for tc in result["tool_calls"]:
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        args = {}

                    tool_result = await execute_tool(tc["function"]["name"], args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

                continue

            # 检查是否有错误信息
            error = result.get("error", "")
            if error:
                reply = f"抱歉，{error}"
                latency = int((time.time() - start) * 1000)
                return {
                    "reply": reply,
                    "tool_calls": all_tool_calls,
                    "usage": result["usage"],
                    "latency_ms": latency,
                }

            reply = result["content"] or ""
            latency = int((time.time() - start) * 1000)

            return {
                "reply": reply,
                "tool_calls": all_tool_calls,
                "usage": result["usage"],
                "latency_ms": latency,
            }

        return {
            "reply": "抱歉，我进行了太多次数据查询仍未得到最终答案，请尝试更具体的提问。",
            "tool_calls": all_tool_calls,
            "usage": {},
            "latency_ms": int((time.time() - start) * 1000),
        }

    async def process_stream(
        self,
        session: ChatSession,
        user_message: str,
        thinking: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """流式处理对话

        事件类型：
            {"type": "reasoning", "content": "..."}         # AI 思考过程
            {"type": "tool_calls_start", "content": N}      # 开始调用 N 个工具
            {"type": "tool_call", "content": {...}}         # 正在调用的工具信息
            {"type": "tool_call_result", "content": {...}}  # 工具返回结果摘要
            {"type": "text", "content": "..."}              # 最终输出的文本片段
            {"type": "usage", "content": {...}}             # token 用量
            {"type": "done"}                                 # 完成
        """
        messages = session.build_messages(self.system_prompt, user_message)

        for round_num in range(config.CHAT_TOOL_CALLS_LIMIT):
            # 使用流式 API 获取本轮回复
            reasoning_buffer = []
            text_buffer = []
            tool_calls_result = None
            usage = None

            async for event in self.client.chat_stream(
                messages=messages,
                tools=self.tools,
                session_id=session.session_id,
                thinking_enabled=thinking,
            ):
                if event["type"] == "reasoning":
                    reasoning_buffer.append(event["content"])
                    # 实时输出思考过程
                    yield {"type": "reasoning", "content": event["content"]}

                elif event["type"] == "text":
                    text_buffer.append(event["content"])
                    # 工具调用轮次中的文本可能是思考的外显
                    # 暂且缓存，最后确定是否输出

                elif event["type"] == "tool_calls":
                    tool_calls_result = event["content"]

                elif event["type"] == "usage":
                    usage = event["content"]

            # ---- 判断本轮是否有工具调用 ----
            if not tool_calls_result:
                # === 最终回复轮次 ===
                has_content = bool(text_buffer or (reasoning_buffer and not text_buffer))

                if not has_content:
                    # 没有任何内容生成时的兜底
                    yield {"type": "text", "content": "已查询到相关数据。"}
                
                for chunk in text_buffer:
                    yield {"type": "text", "content": chunk}

                if reasoning_buffer and not text_buffer:
                    full_reasoning = "".join(reasoning_buffer)
                    yield {"type": "text", "content": full_reasoning}

                if usage:
                    yield {"type": "usage", "content": usage}

                # 保存本轮完整上下文（含 tool_calls），供下一轮对话使用
                msg_context = messages[1:]  # 去掉 system prompt
                # 🔴 关键修复：剥离 reasoning_content（该字段仅用于API输出，不可输入）
                for msg in msg_context:
                    if "reasoning_content" in msg:
                        del msg["reasoning_content"]
                    # 确保 content 不为 None 的字符串（但保留 tool_calls 消息的 content=None 合法格式）
                    if msg.get("content") is None and not msg.get("tool_calls"):
                        msg["content"] = ""
                yield {"type": "message_context", "content": msg_context}

                yield {"type": "done"}
                return

            # === 工具调用轮次 ===
            yield {"type": "tool_calls_start", "content": len(tool_calls_result)}

            # 构建 assistant 消息（必须包含 tool_calls 字段）
            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": tc["type"],
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls_result
                ],
            }
            messages.append(assistant_msg)

            # 逐个执行工具
            for tc in tool_calls_result:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                # 通知前端：正在调用工具
                yield {
                    "type": "tool_call",
                    "content": {
                        "name": tc["function"]["name"],
                        "args": args,
                    },
                }

                # 执行工具
                tool_result = await execute_tool(tc["function"]["name"], args)

                # 通知前端：工具返回结果摘要
                summary = _summarize_tool_result(tc["function"]["name"], tool_result)
                # 将结果数据（截断后）一起发送给前端展示
                result_display = tool_result
                if isinstance(result_display, dict):
                    # 截断过长的结果
                    result_str = json.dumps(result_display, ensure_ascii=False)
                    if len(result_str) > 3000:
                        result_str = result_str[:3000] + '...(截断)'
                    result_display = json.loads(result_str) if result_str.startswith('{') else result_str
                elif isinstance(result_display, list):
                    if len(result_display) > 30:
                        result_display = result_display[:30] + [{"note": f"...共{len(tool_result)}条,仅显示前30条"}]
                yield {
                    "type": "tool_call_result",
                    "content": {
                        "name": tc["function"]["name"],
                        "summary": summary,
                        "result": result_display,
                    },
                }

                # 将工具结果注入 messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            # 进入下一轮（继续用流式 API 获取后续回复）

        # 超过工具调用限制
        yield {"type": "text", "content": "抱歉，数据查询次数过多，请尝试更具体的提问。"}
        yield {"type": "done"}
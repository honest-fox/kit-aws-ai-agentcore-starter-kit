from typing import Any
from collections import OrderedDict
from strands import Agent, tool
import asyncio
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
import os

from strands_tools.browser import AgentCoreBrowser
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from model.load import load_model
from memory.session import get_session_manager

app = BedrockAgentCoreApp()
log = app.logger

# No MCP servers by default: Kit never sends your traffic to third-party
# services unless you opt in. See the MCP extension guide for how to connect
# one (sample client in mcp_client/client.py).
mcp_clients = []

DEFAULT_SYSTEM_PROMPT = """
You are Kit, a working AI agent deployed from Kit — the free, open-source
AI agent starter kit by Honest Fox, running on Amazon Bedrock AgentCore.
Be helpful, direct, and concise. Use tools when appropriate.

You have persistent memory: conversations are stored durably, and facts and
preferences the user shares are remembered across sessions. If relevant
remembered context appears below, use it naturally.
"""

if os.environ.get("KNOWLEDGE_BASE_ID"):
    DEFAULT_SYSTEM_PROMPT += """
You have a knowledge base (the retrieve tool). It currently holds sample
documents about Kookaburra Coffee Co., a fictional Sydney coffee roaster —
always retrieve before answering questions about that company, and prefer
retrieved content over general knowledge for anything it covers.
"""


# Define a collection of tools used by the model
tools = []

_INLINE_FUNCTION_NAMES = set()

# Define a simple function tool
@tool
def add_numbers(a: int, b: int) -> int:
    """Return the sum of two numbers"""
    return a+b
tools.append(add_numbers)

# AgentCore managed tools: code interpreter and browser run in isolated
# AWS-managed sandboxes, not in this container. The runtime role is granted
# access via the connections in agentcore/agentcore.json.
_REGION = os.environ.get("AWS_REGION", "ap-southeast-2")
tools.append(AgentCoreCodeInterpreter(region=_REGION).code_interpreter)
tools.append(AgentCoreBrowser(region=_REGION).browser)

# Knowledge base retrieval (RAG). KNOWLEDGE_BASE_ID is injected by the CDK
# stack; the retrieve tool reads it from the environment. retrieve is a
# module-style tool (TOOL_SPEC + function), so the module itself registers.
if os.environ.get("KNOWLEDGE_BASE_ID"):
    import strands_tools.retrieve

    tools.append(strands_tools.retrieve)



# Add MCP client to tools if available
for mcp_client in mcp_clients:
    if mcp_client:
        tools.append(mcp_client)


def _make_conversation_manager():
    return NullConversationManager()

# Reuses one Agent per (session_id, actor_id). With AgentCore Memory configured
# (the default deployment), each agent gets a session manager that persists every
# turn durably and restores history on cold starts, plus long-term fact/preference
# retrieval. Without memory, history is in-process best-effort. The cache is
# bounded to 128 sessions with LRU eviction so a single process serving many
# sessions cannot leak history between them or grow without limit.
def agent_factory():
    cache = OrderedDict()
    def get_or_create_agent(session_id, actor_id):
        key = (session_id, actor_id)
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        if len(cache) >= 128:
            cache.popitem(last=False)
        session_manager = get_session_manager(session_id, actor_id)
        agent_kwargs = dict(
            model=load_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=tools,
            hooks=[
            ],
        )
        if session_manager is not None:
            agent_kwargs["session_manager"] = session_manager
        else:
            agent_kwargs["conversation_manager"] = _make_conversation_manager()
        cache[key] = Agent(**agent_kwargs)
        return cache[key]
    return get_or_create_agent
get_or_create_agent = agent_factory()


def _extract_actor_id(payload, context) -> str:
    """Actor (user) identity for memory namespacing: payload field, then the
    AgentCore custom user-id header, then a shared default."""
    actor_id = payload.get("actor_id") if isinstance(payload, dict) else None
    if isinstance(actor_id, str) and actor_id:
        return actor_id
    headers = getattr(context, "request_headers", None) or {}
    for header_key, value in headers.items():
        if header_key.lower() == "x-amzn-bedrock-agentcore-runtime-user-id" and value:
            return value
    return "default-user"


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the last message has none."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    messages = list(messages)
    while messages:
        last = messages[-1]
        if not isinstance(last, dict):
            raise ValueError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(isinstance(block, dict) for block in original_content):
            raise ValueError("each message content value must be a list of content blocks")

        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            messages[-1] = {**last, "content": content}
            break
        messages.pop()

    return messages


def _extract_prompt(payload: dict):
    """Accept validated harness messages, tool results, or a plain prompt string."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if "messages" in payload:
        return strip_trailing_tool_use(payload["messages"])
    if "tool_results" in payload:
        tool_results = payload["tool_results"]
        if not isinstance(tool_results, list) or not all(
            isinstance(tool_result, dict) and isinstance(tool_result.get("toolUseId"), str)
            for tool_result in tool_results
        ):
            raise ValueError("tool_results must contain objects with a toolUseId string")
        return [{"role": "user", "content": [{"toolResult": {
            "toolUseId": tr["toolUseId"],
            "status": tr.get("status", "success"),
            "content": tr.get("content", []),
        }} for tr in tool_results]}]
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    return prompt


def _has_inline_function_call(messages) -> bool:
    """Return True if messages contains an assistant toolUse for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES or not isinstance(messages, list):
        return False
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse", {}).get("name") in _INLINE_FUNCTION_NAMES:
                    return True
    return False


def _is_inline_function_call(event: dict) -> bool:
    """Check if a contentBlockStart event is for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES:
        return False
    cbs = event.get("contentBlockStart", {})
    start = cbs.get("start", {})
    tool_use = start.get("toolUse") if isinstance(start, dict) else None
    return tool_use is not None and tool_use.get("name") in _INLINE_FUNCTION_NAMES



@app.entrypoint
async def invoke(payload, context):
    session_id = getattr(context, 'session_id', None) or 'default-session'
    actor_id = _extract_actor_id(payload, context)
    log.info("Invoking agent: session=%s actor=%s", session_id, actor_id)
    agent = get_or_create_agent(session_id, actor_id)

    prompt = _extract_prompt(payload)


    async for event in agent.stream_async(
        prompt,
    ):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()

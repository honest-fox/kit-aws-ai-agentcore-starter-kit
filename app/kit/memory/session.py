"""Durable conversation + long-term memory via Amazon Bedrock AgentCore Memory.

Short-term memory: every conversation turn is synced to AgentCore Memory
events, so sessions survive cold starts and instance changes.
Long-term memory: semantic facts and user preferences extracted by the
memory strategies are retrieved into context at agent initialization.
"""

import logging
import os

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

logger = logging.getLogger(__name__)

# Namespaces must match the strategies in agentcore/agentcore.json.
# relevance_score is deliberately permissive: retrieval queries derive from the
# user's message, and stored facts often score ~0.3-0.5 against oblique
# questions ("do you remember anything about me?"). top_k caps the noise.
LONG_TERM_RETRIEVAL = {
    "/users/{actorId}/facts": RetrievalConfig(top_k=5, relevance_score=0.3),
    "/users/{actorId}/preferences": RetrievalConfig(top_k=5, relevance_score=0.3),
}


def find_memory_id() -> str | None:
    """Locate the AgentCore Memory ID from the environment.

    KIT_MEMORY_ID wins so a deployment can point at an existing memory
    store; otherwise fall back to the variable the CDK stack injects.
    """
    explicit = os.environ.get("KIT_MEMORY_ID")
    if explicit:
        return explicit
    # The AgentCore CDK stack injects MEMORY_<NAME>_ID for each project memory.
    for key, value in sorted(os.environ.items()):
        if key.startswith("MEMORY_") and key.endswith("_ID") and value:
            return value
    return None


def get_session_manager(session_id: str, actor_id: str) -> AgentCoreMemorySessionManager | None:
    """Build a session manager for this session, or None if no memory is configured.

    Returning None lets the agent fall back to in-process history, so Kit
    still works when deployed without a memory resource.
    """
    memory_id = find_memory_id()
    if not memory_id:
        logger.warning("No AgentCore Memory configured; conversation state is in-process only")
        return None
    config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=actor_id,
        retrieval_config=LONG_TERM_RETRIEVAL,
    )
    return AgentCoreMemorySessionManager(config, region_name=os.environ.get("AWS_REGION"))

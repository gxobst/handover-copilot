"""LLM abstraction package for Shift Handover Copilot."""

from app.llm.client import (
    KNOWN_MODELS,
    FakeLLMClient,
    LLMClient,
    VertexLLMClient,
    get_llm_client,
)
from app.llm.exceptions import LLMError, ModelNotFound
from app.llm.prompt import SYSTEM_PROMPT, build_user_prompt

__all__ = [
    "KNOWN_MODELS",
    "FakeLLMClient",
    "LLMClient",
    "VertexLLMClient",
    "get_llm_client",
    "LLMError",
    "ModelNotFound",
    "SYSTEM_PROMPT",
    "build_user_prompt",
]

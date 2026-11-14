"""Exceptions for LLM client operations."""


class LLMError(Exception):
    """Base exception for all LLM client and generation errors."""

    pass


class ModelNotFound(LLMError):
    """Raised when a requested model is unrecognized, unavailable, or deprecated."""

    pass

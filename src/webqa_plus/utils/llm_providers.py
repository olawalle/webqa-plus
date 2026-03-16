"""Gemini LLM provider factory and configuration."""

import os
from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI


DEFAULT_MODEL = "gemini-2.0-flash"
PROVIDER = "gemini"


class LLMConfig:
    """Configuration for the Gemini LLM provider."""

    def __init__(
        self,
        provider: str = PROVIDER,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        base_url: Optional[str] = None,
        multimodal: bool = True,
        vertex_ai: bool = False,
        **kwargs: Any,
    ):
        """Initialize Gemini LLM configuration.

        Args:
            provider: Must be "gemini" (only supported provider)
            api_key: Google AI API key (or Vertex AI key)
            model: Gemini model name
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            base_url: Optional custom API endpoint
            multimodal: Enable screenshot injection for vision-based QA
            vertex_ai: Use Vertex AI endpoint instead of AI Studio
            **kwargs: Additional provider-specific options
        """
        if provider != PROVIDER:
            raise ValueError(
                f"Only 'gemini' provider is supported. Got: {provider}"
            )
        self.provider = PROVIDER
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.base_url = base_url
        self.multimodal = multimodal
        self.vertex_ai = vertex_ai
        self.extra_kwargs = kwargs

    def create_llm(self) -> BaseChatModel:
        """Create and return a ChatGoogleGenerativeAI instance."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        if self.api_key:
            kwargs["google_api_key"] = self.api_key
        kwargs.update(self.extra_kwargs)
        return ChatGoogleGenerativeAI(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "base_url": self.base_url,
            "multimodal": self.multimodal,
            "vertex_ai": self.vertex_ai,
            **self.extra_kwargs,
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "LLMConfig":
        """Create configuration from dictionary."""
        return cls(**config_dict)


# Legacy alias kept so imports don't break
class LLMProvider:
    """Stub kept for backward-compat imports."""
    GEMINI = "gemini"


def get_default_model_for_provider(provider: str = PROVIDER) -> str:
    """Return the default Gemini model name."""
    return DEFAULT_MODEL


def validate_provider_config(config: Dict[str, Any]) -> Dict[str, str]:
    """Validate Gemini provider configuration.

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary of validation errors by field
    """
    errors: Dict[str, str] = {}

    provider = config.get("provider", PROVIDER)
    if provider != PROVIDER:
        errors["provider"] = f"Only 'gemini' is supported. Got: {provider}"

    if not config.get("api_key") and not os.getenv("GOOGLE_API_KEY"):
        errors["api_key"] = "API key required. Set GOOGLE_API_KEY environment variable."

    return errors

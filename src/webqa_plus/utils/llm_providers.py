"""LLM provider factory and configuration for multi-provider support."""

import os
from enum import Enum
from typing import Any, Dict, Optional, Union

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None

try:
    from langchain_community.chat_models import ChatOpenRouter
except ImportError:
    ChatOpenRouter = None


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


class LLMConfig:
    """Configuration for an LLM provider."""

    def __init__(
        self,
        provider: Union[str, LLMProvider] = LLMProvider.OPENAI,
        api_key: Optional[str] = None,
        model: str = "gpt-4-turbo-preview",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize LLM configuration.

        Args:
            provider: The LLM provider to use
            api_key: API key for the provider
            model: Model name to use
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            base_url: Optional base URL for API
            **kwargs: Additional provider-specific options
        """
        self.provider = LLMProvider(provider)
        self.api_key = api_key or self._get_api_key_from_env()
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.base_url = base_url
        self.extra_kwargs = kwargs

    def _get_api_key_from_env(self) -> str:
        """Get API key from environment variables based on provider."""
        env_vars = {
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            LLMProvider.OPENROUTER: "OPENROUTER_API_KEY",
        }
        env_var = env_vars.get(self.provider)
        return os.getenv(env_var, "") if env_var else ""

    def create_llm(self) -> BaseChatModel:
        """Create and return the appropriate LLM instance."""
        if self.provider == LLMProvider.OPENAI:
            return self._create_openai_llm()
        elif self.provider == LLMProvider.ANTHROPIC:
            return self._create_anthropic_llm()
        elif self.provider == LLMProvider.OPENROUTER:
            return self._create_openrouter_llm()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _create_openai_llm(self) -> ChatOpenAI:
        """Create OpenAI LLM instance."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        kwargs.update(self.extra_kwargs)
        return ChatOpenAI(**kwargs)

    def _create_anthropic_llm(self) -> ChatAnthropic:
        """Create Anthropic (Claude) LLM instance."""
        if ChatAnthropic is None:
            raise ImportError(
                "langchain-anthropic is required for Anthropic provider. "
                "Install with: uv add langchain-anthropic"
            )

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["anthropic_api_url"] = self.base_url
        kwargs.update(self.extra_kwargs)
        return ChatAnthropic(**kwargs)

    def _create_openrouter_llm(self) -> ChatOpenAI:
        """Create OpenRouter LLM instance (uses OpenAI-compatible API)."""
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url or "https://openrouter.ai/api/v1",
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Add OpenRouter-specific headers
        kwargs["default_headers"] = {
            "HTTP-Referer": "https://github.com/yourusername/webqa-plus",
            "X-Title": "WebQA-Plus",
        }
        kwargs.update(self.extra_kwargs)
        return ChatOpenAI(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "provider": self.provider.value,
            "api_key": self.api_key,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "base_url": self.base_url,
            **self.extra_kwargs,
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "LLMConfig":
        """Create configuration from dictionary."""
        return cls(**config_dict)


def get_default_model_for_provider(provider: Union[str, LLMProvider]) -> str:
    """Get the default model for a provider.

    Args:
        provider: The LLM provider

    Returns:
        Default model name for the provider
    """
    defaults = {
        LLMProvider.OPENAI: "gpt-4-turbo-preview",
        LLMProvider.ANTHROPIC: "claude-3-opus-20240229",
        LLMProvider.OPENROUTER: "anthropic/claude-3-opus",
    }
    return defaults.get(LLMProvider(provider), "gpt-4-turbo-preview")


def validate_provider_config(config: Dict[str, Any]) -> Dict[str, str]:
    """Validate provider configuration and return errors.

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary of validation errors by field
    """
    errors: Dict[str, str] = {}

    provider = config.get("provider", "openai")
    try:
        LLMProvider(provider)
    except ValueError:
        errors["provider"] = f"Invalid provider: {provider}"

    if not config.get("api_key"):
        # Check environment variable
        env_vars = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        env_var = env_vars.get(provider)
        if env_var and not os.getenv(env_var):
            errors["api_key"] = f"API key required. Set {env_var} environment variable."

    return errors

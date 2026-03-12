"""Configuration management for WebQA-Plus."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from webqa_plus.utils.llm_providers import LLMConfig, LLMProvider, get_default_model_for_provider


class LLMProviderConfig(BaseModel):
    """Generic LLM provider configuration."""

    provider: str = Field(
        default="openai", description="LLM provider (openai, anthropic, openrouter)"
    )
    api_key: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", ""),
        description="API key for the provider",
    )
    model: str = Field(default="gpt-4-turbo-preview", description="Model name to use")
    max_tokens: int = Field(default=4096, description="Maximum tokens to generate")
    temperature: float = Field(default=0.3, description="Temperature for generation")
    base_url: Optional[str] = Field(default=None, description="Optional base URL for API")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name."""
        valid_providers = ["openai", "anthropic", "openrouter"]
        if v not in valid_providers:
            raise ValueError(f"Provider must be one of {valid_providers}")
        return v

    @model_validator(mode="after")
    def set_api_key_from_env(self) -> "LLMProviderConfig":
        """Set API key from environment if not provided."""
        if not self.api_key:
            env_vars = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
            }
            env_var = env_vars.get(self.provider)
            if env_var and os.getenv(env_var):
                api_key = os.getenv(env_var)
                if api_key is not None:
                    self.api_key = api_key
        return self

    @model_validator(mode="after")
    def set_default_model(self) -> "LLMProviderConfig":
        """Set default model based on provider if not specified."""
        if self.model == "gpt-4-turbo-preview" and self.provider != "openai":
            # User didn't specify a model, use provider default
            self.model = get_default_model_for_provider(self.provider)
        return self

    def create_llm_config(self) -> LLMConfig:
        """Create LLMConfig instance from this configuration."""
        return LLMConfig(
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            base_url=self.base_url,
        )


class OpenAIConfig(BaseModel):
    """OpenAI API configuration (deprecated, use LLMProviderConfig)."""

    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    model: str = "gpt-4-turbo-preview"
    max_tokens: int = 4096
    temperature: float = 0.3


class PlaywrightConfig(BaseModel):
    """Playwright browser configuration."""

    browser: str = "chromium"
    headless: bool = True
    viewport: Dict[str, int] = Field(default_factory=lambda: {"width": 1920, "height": 1080})
    timeout: int = 30000
    action_timeout: int = 5000


class MCPConfig(BaseModel):
    """MCP server configuration."""

    server_url: str = "http://localhost:3000"
    timeout: int = 10000


class AuthConfig(BaseModel):
    """Authentication configuration."""

    enabled: bool = False
    email: Optional[str] = None
    password: Optional[str] = None


class TestingConfig(BaseModel):
    """Testing behavior configuration."""

    url: str = ""
    mode: str = "stealth"
    max_steps: int = 200
    max_depth: int = 10
    screenshot_on_error: bool = True
    screenshot_on_action: bool = True
    hidden_menu_expander: bool = True
    deep_traversal: bool = True
    path_discovery_boost: int = 1
    form_validation_pass: bool = True
    email_verification_enabled: bool = False
    email_provider: str = "1secmail"
    email_provider_base_url: str = "https://www.1secmail.com/api/v1/"
    email_poll_timeout_seconds: int = 120
    email_poll_interval_seconds: int = 5
    email_request_timeout_seconds: float = 12.0
    output_dir: str = "./reports"


class CostConfig(BaseModel):
    """Cost guardrails configuration."""

    max_llm_calls: int = 500
    max_llm_tokens: int = 100000
    estimated_cost_per_1k_tokens: float = 0.01


class ReportConfig(BaseModel):
    """Report generation configuration."""

    template_dir: str = "src/webqa_plus/reporter"
    output_format: str = "pdf"
    include_screenshots: bool = True
    include_console_logs: bool = True
    include_network_logs: bool = True


class VisualConfig(BaseModel):
    """Visual mode overlay configuration."""

    overlay_position: str = "top-right"
    overlay_opacity: float = 0.9
    update_interval_ms: int = 100


class AppConfig(BaseModel):
    """Main application configuration."""

    # Primary LLM configuration (new way)
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)

    # Legacy OpenAI configuration (deprecated, for backward compatibility)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)

    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    objectives: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def sync_legacy_config(self) -> "AppConfig":
        """Sync legacy openai config with new llm config if llm not explicitly set."""
        # If legacy openai config has values but llm is default, migrate
        if self.openai.api_key and not self.llm.api_key:
            self.llm = LLMProviderConfig(
                provider="openai",
                api_key=self.openai.api_key,
                model=self.openai.model,
                max_tokens=self.openai.max_tokens,
                temperature=self.openai.temperature,
            )
        return self

    def get_llm_config(self) -> LLMConfig:
        """Get the LLM configuration for creating LLM instances."""
        return self.llm.create_llm_config()


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file or return defaults."""
    config_dict = {}

    if config_path and config_path.exists():
        with open(config_path, "r") as f:
            yaml_content = f.read()
            # Substitute environment variables
            yaml_content = os.path.expandvars(yaml_content)
            config_dict = yaml.safe_load(yaml_content) or {}

    # Override with environment variables
    if os.getenv("OPENAI_API_KEY"):
        config_dict.setdefault("openai", {})["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("ANTHROPIC_API_KEY"):
        config_dict.setdefault("llm", {})["provider"] = "anthropic"
        config_dict.setdefault("llm", {})["api_key"] = os.getenv("ANTHROPIC_API_KEY")
    if os.getenv("OPENROUTER_API_KEY"):
        config_dict.setdefault("llm", {})["provider"] = "openrouter"
        config_dict.setdefault("llm", {})["api_key"] = os.getenv("OPENROUTER_API_KEY")

    return AppConfig(**config_dict)

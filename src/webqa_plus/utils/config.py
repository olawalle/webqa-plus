"""Configuration management for WebQA-Plus."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from webqa_plus.utils.llm_providers import LLMConfig, LLMProvider, get_default_model_for_provider


class LLMProviderConfig(BaseModel):
    """Gemini LLM provider configuration."""

    provider: str = Field(
        default="gemini", description="LLM provider (gemini only)"
    )
    api_key: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""),
        description="Google AI API key (GOOGLE_API_KEY)",
    )
    model: str = Field(default="gemini-2.0-flash", description="Gemini model name")
    max_tokens: int = Field(default=4096, description="Maximum tokens to generate")
    temperature: float = Field(default=0.3, description="Temperature for generation")
    base_url: Optional[str] = Field(default=None, description="Optional custom API endpoint")
    multimodal: bool = Field(default=True, description="Enable screenshot injection for vision-based QA")
    vertex_ai: bool = Field(default=False, description="Use Vertex AI endpoint")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate provider name."""
        if v != "gemini":
            raise ValueError("Only 'gemini' provider is supported")
        return v

    @model_validator(mode="after")
    def set_api_key_from_env(self) -> "LLMProviderConfig":
        """Set API key from GOOGLE_API_KEY environment variable if not provided."""
        if not self.api_key:
            key = os.getenv("GOOGLE_API_KEY", "")
            if key:
                self.api_key = key
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
            multimodal=self.multimodal,
            vertex_ai=self.vertex_ai,
        )


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
    dom_exploration_enabled: bool = True
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

    overlay_position: str = "bottom-right"
    overlay_opacity: float = 0.9
    update_interval_ms: int = 100


class AppConfig(BaseModel):
    """Main application configuration."""

    # Gemini LLM configuration
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)

    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    objectives: Optional[Dict[str, Any]] = None

    def get_llm_config(self) -> LLMConfig:
        """Get the Gemini LLM configuration."""
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

    # Override with GOOGLE_API_KEY environment variable
    if os.getenv("GOOGLE_API_KEY"):
        config_dict.setdefault("llm", {})["provider"] = "gemini"
        config_dict.setdefault("llm", {})["api_key"] = os.getenv("GOOGLE_API_KEY")

    return AppConfig(**config_dict)

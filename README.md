# WebQA-Plus

**Best-of-all-worlds autonomous AI web QA tester**

WebQA-Plus is a production-ready CLI application that combines the power of:
- 🤖 **LangGraph** - Stateful agent orchestration
- 🎭 **Playwright MCP** - Microsoft Playwright with structured accessibility trees
- 🔍 **WebQA-Agent** - Intelligent web exploration and testing
- 💬 **Multi-Provider LLMs** - OpenAI, Anthropic Claude, OpenRouter, and more
- 📊 **Rich** - Beautiful terminal dashboards
- 📄 **WeasyPrint** - Professional PDF reports

## Features

- **Dual Runtime Modes**: Visual (headed with live overlay) or Stealth (headless)
- **Automatic Authentication**: Login form detection with credential injection
- **Smart Exploration**: WebQA-Agent based with MCP accessibility trees
- **4-Agent Architecture**: Explorer → Tester → Validator → Reporter
- **Self-Healing Locators**: MCP-powered element detection
- **Live Progress Tracking**: Browser overlay + Terminal dashboard
- **Beautiful PDF Reports**: Mermaid diagrams, screenshots, performance metrics
- **Cost Guardrails**: LLM usage limits and step budgets

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/webqa-plus.git
cd webqa-plus

# Install with uv
uv sync

# Install Playwright browsers
uv run playwright install chromium

# Verify installation
uv run webqa-plus --help
```

## Quick Start

### Basic Test (Stealth Mode)
```bash
uv run webqa-plus test --url https://example.com --max-steps 50
```

### With Authentication
```bash
uv run webqa-plus test \
  --url https://app.example.com \
  --email user@example.com \
  --password secret123 \
  --mode visual
```

### Full Configuration
```bash
uv run webqa-plus test \
  --url https://example.com \
  --mode visual \
  --max-steps 200 \
  --output-dir ./reports \
  --config config.yaml
```

## Configuration

Copy the example configuration:
```bash
cp config.yaml.example config.yaml
```

### LLM Provider Configuration

WebQA-Plus supports multiple LLM providers. Configure in `config.yaml`:

**OpenAI (default):**
```yaml
llm:
  provider: "openai"
  api_key: "${OPENAI_API_KEY}"
  model: "gpt-4-turbo-preview"
  max_tokens: 4096
  temperature: 0.3
```

**Anthropic Claude:**
```yaml
llm:
  provider: "anthropic"
  api_key: "${ANTHROPIC_API_KEY}"
  model: "claude-3-opus-20240229"
  max_tokens: 4096
  temperature: 0.3
```

**OpenRouter:**
```yaml
llm:
  provider: "openrouter"
  api_key: "${OPENROUTER_API_KEY}"
  model: "anthropic/claude-3-opus"
  max_tokens: 4096
  temperature: 0.3
```

### Other Configuration Options

Edit `config.yaml` to customize:
- LLM provider settings
- Playwright settings
- MCP server configuration
- Cost limits and guardrails
- Report templates

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        WebQA-Plus CLI                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Orchestrator                    │
├─────────────┬──────────────┬──────────────┬─────────────────┤
│  Explorer   │   Tester     │   Validator  │    Reporter     │
│    Agent    │    Agent     │     Agent    │     Agent       │
├─────────────┼──────────────┼──────────────┼─────────────────┤
│ • WebQA     │ • Smart      │ • LLM Check  │ • PDF Gen       │
│ • MCP Tree  │ • Inputs     │ • Visual     │ • Screenshots   │
│ • Planning  │ • Auth       │ • Console    │ • Flows         │
└─────────────┴──────────────┴──────────────┴─────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Playwright + MCP Server                         │
│         (Headed/Headless, Auth, Screenshots)                │
└─────────────────────────────────────────────────────────────┘
```

## Custom Business Objectives

Add custom testing objectives by creating a `objectives.yaml`:

```yaml
objectives:
  - name: "checkout_flow"
    description: "Test complete checkout process"
    critical_paths:
      - ["add_to_cart", "view_cart", "checkout", "payment", "confirmation"]
    
  - name: "user_registration"
    description: "Test user signup and onboarding"
    required_elements:
      - "input[name='email']"
      - "input[name='password']"
      - "button[type='submit']"
```

Then run with:
```bash
uv run webqa-plus test --url https://example.com --objectives objectives.yaml
```

## Development

```bash
# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check --fix src/

# Type checking
uv run mypy src/
```

## Docker

```bash
docker build -t webqa-plus .
docker run -v $(pwd)/reports:/app/reports webqa-plus \
  test --url https://example.com --mode stealth
```

## License

MIT License - see LICENSE file for details.

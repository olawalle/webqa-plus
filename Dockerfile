# WebQA-Plus Dockerfile
# Multi-stage build for production-ready image

# ── Stage 1: Build React frontend ──────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig*.json frontend/postcss.config.js frontend/tailwind.config.ts ./
COPY frontend/src ./src
COPY frontend/public ./public
RUN npm run build

# ── Stage 2: Build Python dependencies ─────────────────────────────────────
FROM python:3.12-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libpango1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libpangocairo-1.0-0 \
    libxml2 \
    libxmlsec1-openssl \
    libxmlsec1-dev \
    pkg-config \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Set workdir
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./
COPY README.md ./

# Install dependencies
RUN /root/.cargo/bin/uv pip install --system -e "."

# Final stage
FROM python:3.12-slim as production

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpango1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libpangocairo-1.0-0 \
    libxml2 \
    libxmlsec1-openssl \
    libxmlsec1-dev \
    chromium \
    chromium-driver \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set workdir
WORKDIR /app

# Copy application code
COPY src/ ./src/
COPY config.yaml.example ./

# Copy built React frontend so FastAPI can serve it in production mode
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Create reports directory
RUN mkdir -p /app/reports

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin/chromium
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium

# Install Playwright browsers
RUN playwright install chromium

# Create non-root user
RUN useradd -m -u 1000 webqa && chown -R webqa:webqa /app
USER webqa

# Expose port (Cloud Run uses PORT env var, defaults to 8080)
EXPOSE 8080

# Default: launch the web server in production mode
ENTRYPOINT ["webqa-plus"]
CMD ["web", "--host", "0.0.0.0", "--port", "8080", "--no-reload"]

# Labels
LABEL maintainer="WebQA-Plus Team"
LABEL version="1.0.0"
LABEL description="Best-of-all-worlds autonomous AI web QA tester"

/**
 * WebQA-Plus Web Interface
 * Handles provider selection, configuration, and test execution
 */

class WebQAPlusApp {
  constructor() {
    this.providers = [];
    this.selectedProvider = null;
    this.currentSessionId = null;
    this.websocket = null;
    this.pollInterval = null;
    this.displayedLogs = new Set();
    this.hasShownRunFailure = false;
    this.lastTestConfig = null;

    this.init();
  }

  async init() {
    await this.loadProviders();
    this.setupEventListeners();
    this.updateTemperatureDisplay();
    this.updateStepsDisplay();
  }

  async loadProviders() {
    try {
      const response = await fetch("/api/providers");
      const data = await response.json();
      this.providers = data.providers;
      this.renderProviders();
    } catch (error) {
      console.error("Failed to load providers:", error);
      this.showError("Failed to load providers. Please refresh the page.");
    }
  }

  renderProviders() {
    const grid = document.getElementById("provider-grid");
    grid.innerHTML = this.providers
      .map(
        (provider) => `
            <div class="provider-card" data-provider-id="${provider.id}">
                <div class="icon">${provider.icon}</div>
                <h4>${provider.name}</h4>
                <p>${provider.description}</p>
            </div>
        `,
      )
      .join("");

    // Add click handlers
    grid.querySelectorAll(".provider-card").forEach((card) => {
      card.addEventListener("click", () =>
        this.selectProvider(card.dataset.providerId),
      );
    });
  }

  selectProvider(providerId) {
    // Remove previous selection
    document.querySelectorAll(".provider-card").forEach((card) => {
      card.classList.remove("selected");
    });

    // Add selection to clicked card
    const selectedCard = document.querySelector(
      `[data-provider-id="${providerId}"]`,
    );
    selectedCard.classList.add("selected");

    // Update selected provider
    this.selectedProvider = this.providers.find((p) => p.id === providerId);

    // Show provider settings
    document.getElementById("provider-settings-card").style.display = "block";

    // Update API key hint
    const apiKeyHint = document.getElementById("api-key-hint");
    apiKeyHint.textContent = `Enter your ${this.selectedProvider.name} API key (env: ${this.selectedProvider.env_var})`;

    // Load models for this provider
    this.loadModels(providerId);

    // Update start button
    this.validateForm();

    // Scroll to settings
    document
      .getElementById("provider-settings-card")
      .scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async loadModels(providerId) {
    try {
      const apiKey = document.getElementById("api-key").value.trim();
      const query = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
      const response = await fetch(`/api/models/${providerId}${query}`);
      const data = await response.json();

      const modelSelect = document.getElementById("model");
      const previousSelection = modelSelect.value;

      modelSelect.innerHTML = data.models
        .map((model) => `<option value="${model.id}">${model.name}</option>`)
        .join("");

      if (!data.models || data.models.length === 0) {
        modelSelect.innerHTML = `<option value="">No models available</option>`;
        return;
      }

      const hasPrevious = data.models.some(
        (model) => model.id === previousSelection,
      );
      if (hasPrevious) {
        modelSelect.value = previousSelection;
      } else {
        const preferred =
          data.default_model || this.selectedProvider?.default_model;
        const hasPreferred = data.models.some(
          (model) => model.id === preferred,
        );
        modelSelect.value = hasPreferred ? preferred : data.models[0].id;
      }

      this.validateForm();
    } catch (error) {
      console.error("Failed to load models:", error);
    }
  }

  setupEventListeners() {
    // Navigation
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        this.switchSection(section);
      });
    });

    // Toggle API key visibility
    document.getElementById("toggle-key").addEventListener("click", () => {
      const input = document.getElementById("api-key");
      input.type = input.type === "password" ? "text" : "password";
    });

    // Refetch models after API key edits
    const apiKeyInput = document.getElementById("api-key");
    apiKeyInput.addEventListener("change", () => {
      if (this.selectedProvider) {
        this.loadModels(this.selectedProvider.id);
      }
    });

    // Temperature slider
    document.getElementById("temperature").addEventListener("input", () => {
      this.updateTemperatureDisplay();
    });

    // Max steps slider
    document.getElementById("max-steps").addEventListener("input", () => {
      this.updateStepsDisplay();
    });

    // Auth checkbox
    document.getElementById("auth-enabled").addEventListener("change", (e) => {
      const authFields = document.getElementById("auth-fields");
      authFields.style.display = e.target.checked ? "block" : "none";
    });

    // Form inputs
    document.querySelectorAll("input, select").forEach((input) => {
      input.addEventListener("change", () => this.validateForm());
      input.addEventListener("input", () => this.validateForm());
    });

    // Start test button
    document
      .getElementById("start-test-btn")
      .addEventListener("click", () => this.startTest());

    // Back to setup button
    document
      .getElementById("back-to-setup-btn")
      .addEventListener("click", () => {
        this.switchSection("setup");
      });

    // Stop test button
    document
      .getElementById("stop-test-btn")
      .addEventListener("click", () => this.stopTest());

    // Re-run button
    document.getElementById("rerun-test-btn").addEventListener("click", () => {
      if (!this.lastTestConfig) {
        this.showError("No previous test configuration found to rerun.");
        return;
      }
      this.startTest({ ...this.lastTestConfig });
    });

    // Refresh reports when viewing
    document
      .querySelector('[data-section="reports"]')
      .addEventListener("click", () => {
        this.loadReports();
      });
  }

  updateTemperatureDisplay() {
    const value = document.getElementById("temperature").value;
    document.getElementById("temperature-value").textContent = value;
  }

  updateStepsDisplay() {
    const value = document.getElementById("max-steps").value;
    document.getElementById("steps-value").textContent = value;
  }

  switchSection(section) {
    // Update navigation
    document.querySelectorAll(".nav-item").forEach((item) => {
      item.classList.remove("active");
    });
    document
      .querySelector(`[data-section="${section}"]`)
      .classList.add("active");

    // Update content
    document.querySelectorAll(".content-section").forEach((s) => {
      s.classList.remove("active");
    });
    document.getElementById(`${section}-section`).classList.add("active");
  }

  validateForm() {
    const hasProvider = !!this.selectedProvider;
    const apiKey = document.getElementById("api-key").value.trim();
    const model = document.getElementById("model").value.trim();
    const targetUrl = document.getElementById("target-url").value.trim();
    const authEnabled = document.getElementById("auth-enabled").checked;
    const authEmail = document.getElementById("auth-email").value.trim();
    const authPassword = document.getElementById("auth-password").value.trim();

    const hasCoreFields =
      hasProvider && apiKey !== "" && model !== "" && targetUrl !== "";
    const hasAuthFields =
      !authEnabled || (authEmail !== "" && authPassword !== "");

    const isValid = hasCoreFields && hasAuthFields;
    document.getElementById("start-test-btn").disabled = !isValid;
  }

  getCurrentConfig() {
    return {
      provider: this.selectedProvider?.id || "openai",
      api_key: document.getElementById("api-key").value,
      model: document.getElementById("model").value,
      max_tokens: parseInt(document.getElementById("max-tokens").value),
      temperature: parseFloat(document.getElementById("temperature").value),
      url: document.getElementById("target-url").value,
      auth_enabled: document.getElementById("auth-enabled").checked,
      auth_email: document.getElementById("auth-email").value,
      auth_password: document.getElementById("auth-password").value,
      mode: document.getElementById("test-mode").value,
      max_steps: parseInt(document.getElementById("max-steps").value),
      browser: document.getElementById("browser").value,
      headless: document.getElementById("test-mode").value === "stealth",
      screenshot_on_error: document.querySelector(
        'input[name="screenshot_on_error"]',
      ).checked,
      screenshot_on_action: document.querySelector(
        'input[name="screenshot_on_action"]',
      ).checked,
      output_dir: "./reports",
    };
  }

  async startTest(configOverride = null) {
    this.clearMonitor();

    const config = configOverride || this.getCurrentConfig();
    this.lastTestConfig = { ...config };
    this.setRerunButton(false);

    // Show loading
    document.getElementById("loading-overlay").style.display = "flex";

    try {
      const response = await fetch("/api/test/start", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(config),
      });

      const data = await response.json();

      if (response.ok) {
        this.currentSessionId = data.session_id;
        document.getElementById("loading-overlay").style.display = "none";
        this.switchSection("test");
        this.connectWebSocket(data.session_id);
        this.log("Test started successfully", "success");
      } else {
        throw new Error(data.error || "Failed to start test");
      }
    } catch (error) {
      document.getElementById("loading-overlay").style.display = "none";
      this.log(`Error: ${error.message}`, "error");
      this.setRerunButton(!!this.lastTestConfig);
      this.showError(`Failed to start test: ${error.message}`);
    }
  }

  connectWebSocket(sessionId) {
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/${sessionId}`;
    this.websocket = new WebSocket(wsUrl);

    this.websocket.onopen = () => {
      this.log("Connected to test session", "info");
      this.enableStopButton();
    };

    this.websocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.updateTestStatus(data);
    };

    this.websocket.onclose = () => {
      this.log("Disconnected from test session", "warning");
      this.disableStopButton();
      // Poll for final status
      this.pollTestStatus(sessionId);
    };

    this.websocket.onerror = (error) => {
      this.log("WebSocket error", "error");
      console.error("WebSocket error:", error);
    };
  }

  updateTestStatus(data) {
    // Update status badge
    const statusBadge = document.getElementById("test-status");
    statusBadge.textContent =
      data.status.charAt(0).toUpperCase() + data.status.slice(1);
    statusBadge.className = "status-badge " + data.status;

    // Update progress
    const progress = data.progress || 0;
    document.getElementById("progress-fill").style.width = `${progress}%`;
    document.getElementById("progress-text").textContent =
      `${Math.round(progress)}%`;

    // Update stats
    document.getElementById("stat-steps").textContent = data.current_step;
    document.getElementById("stat-urls").textContent = data.urls_visited;
    document.getElementById("stat-flows").textContent = data.flows_discovered;
    document.getElementById("stat-results").textContent = data.test_results;

    // Update logs
    if (data.logs && data.logs.length > 0) {
      data.logs.forEach((log) => {
        const logId = `${log.ts || ""}:${log.level || "info"}:${log.message || ""}`;
        if (!this.displayedLogs.has(logId)) {
          this.displayedLogs.add(logId);
          this.log(log.message || "Event", log.level || "info");
        }
      });
    }

    // Check if completed
    if (data.status === "completed" || data.status === "failed") {
      this.disableStopButton();
      this.setRerunButton(true);
      this.loadReports();

      if (
        data.status === "failed" &&
        !this.hasShownRunFailure &&
        Array.isArray(data.errors) &&
        data.errors.length > 0
      ) {
        this.hasShownRunFailure = true;
        const debugTail =
          Array.isArray(data.debug_errors) && data.debug_errors.length > 0
            ? `\n\nDebug details:\n${data.debug_errors[data.debug_errors.length - 1]}`
            : "";
        this.showError(`${data.errors[0]}${debugTail}`);
      }
    }

    if (data.status === "stopped") {
      this.disableStopButton();
      this.setRerunButton(true);
    }
  }

  pollTestStatus(sessionId) {
    this.pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/api/test/${sessionId}/status`);
        const data = await response.json();
        this.updateTestStatus(data);

        if (data.status === "completed" || data.status === "failed") {
          clearInterval(this.pollInterval);
        }
      } catch (error) {
        console.error("Failed to poll status:", error);
      }
    }, 2000);
  }

  async stopTest() {
    if (!this.currentSessionId) return;

    try {
      const response = await fetch(`/api/test/${this.currentSessionId}/stop`, {
        method: "POST",
      });

      if (response.ok) {
        this.log("Test stopped by user", "warning");
        this.disableStopButton();
      }
    } catch (error) {
      console.error("Failed to stop test:", error);
    }
  }

  enableStopButton() {
    const btn = document.getElementById("stop-test-btn");
    btn.disabled = false;
    btn.classList.add("btn-danger");
  }

  disableStopButton() {
    const btn = document.getElementById("stop-test-btn");
    btn.disabled = true;
    btn.classList.remove("btn-danger");
  }

  setRerunButton(enabled) {
    const btn = document.getElementById("rerun-test-btn");
    btn.disabled = !enabled;
  }

  log(message, level = "info") {
    const container = document.getElementById("log-content");
    const time = new Date().toLocaleTimeString();

    const entry = document.createElement("div");
    entry.className = `log-entry log-${level}`;
    entry.innerHTML = `
            <span class="log-time">${time}</span>
            <span class="log-message">${message}</span>
        `;

    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
  }

  clearMonitor() {
    this.displayedLogs.clear();
    this.hasShownRunFailure = false;
    document.getElementById("progress-fill").style.width = "0%";
    document.getElementById("progress-text").textContent = "0%";
    document.getElementById("stat-steps").textContent = "0";
    document.getElementById("stat-urls").textContent = "0";
    document.getElementById("stat-flows").textContent = "0";
    document.getElementById("stat-results").textContent = "0";

    const logContent = document.getElementById("log-content");
    logContent.innerHTML = `
            <div class="log-entry log-info">
                <span class="log-time">--:--:--</span>
                <span class="log-message">Preparing test session...</span>
            </div>
        `;
  }

  async loadReports() {
    try {
      const response = await fetch("/api/reports");
      const data = await response.json();

      const container = document.getElementById("reports-list");

      if (data.reports.length === 0) {
        container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">📭</div>
                        <h4>No Reports Yet</h4>
                        <p>Run your first test to generate a report</p>
                    </div>
                `;
        return;
      }

      container.innerHTML = data.reports
        .map(
          (report) => `
                <div class="report-item">
                    <div class="report-info">
                        <div class="report-name">${report.filename}</div>
                        <div class="report-meta">
                            ${new Date(report.created).toLocaleString()} • ${this.formatFileSize(report.size)}
                        </div>
                    </div>
                    <div class="report-actions">
                        <button class="btn btn-secondary" onclick="window.open('/api/reports/${encodeURIComponent(report.filename)}', '_blank')">
                            📄 View
                        </button>
                        <button class="btn btn-primary" onclick="window.location.href='/api/reports/${encodeURIComponent(report.filename)}?download=true'">
                            ⬇️ Download
                        </button>
                    </div>
                </div>
            `,
        )
        .join("");
    } catch (error) {
      console.error("Failed to load reports:", error);
    }
  }

  formatFileSize(bytes) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  showError(message) {
    // Simple error display - could be enhanced with a toast notification
    alert(message);
  }
}

// Initialize app when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  new WebQAPlusApp();
});

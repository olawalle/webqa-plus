import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bot,
  Brain,
  Eye,
  FileText,
  Globe,
  Play,
  RefreshCw,
  Shield,
  Square,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

const GEMINI_PROVIDER = "gemini";

const GEMINI_MODELS = [
  { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
  { id: "gemini-2.0-flash-lite", name: "Gemini 2.0 Flash Lite" },
  { id: "gemini-2.5-pro-preview-03-25", name: "Gemini 2.5 Pro Preview" },
  { id: "gemini-1.5-pro", name: "Gemini 1.5 Pro" },
  { id: "gemini-1.5-flash", name: "Gemini 1.5 Flash" },
];

type LogEntry = {
  ts?: string;
  level?: string;
  message?: string;
};

type LlmTurn = {
  ts: string;
  agent: string;
  prompt: string;
  response: string;
};

type TestStatus = {
  status: string;
  progress: number;
  current_step: number;
  max_steps: number;
  urls_visited: number;
  flows_discovered: number;
  test_results: number;
  logs: LogEntry[];
  errors: string[];
  debug_errors?: string[];
  current_objective?: string;
  llm_turns?: LlmTurn[];
  learning_memory?: string[];
};

type ReportItem = {
  filename: string;
  created: string;
  size: number;
};

function App() {
  const [models, setModels] = useState(GEMINI_MODELS);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [steerInstruction, setSteerInstruction] = useState("");
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [llmTurns, setLlmTurns] = useState<LlmTurn[]>([]);
  const [activeTab, setActiveTab] = useState<"logs" | "ai" | "memory">("logs");
  const [aiFilter, setAiFilter] = useState<string>("all");
  const [expandedTurns, setExpandedTurns] = useState<Set<number>>(new Set());
  const aiScrollRef = useRef<HTMLDivElement>(null);
  const [testStatus, setTestStatus] = useState<TestStatus>({
    status: "ready",
    progress: 0,
    current_step: 0,
    max_steps: 200,
    urls_visited: 0,
    flows_discovered: 0,
    test_results: 0,
    logs: [],
    errors: [],
  });

  const [form, setForm] = useState({
    api_key: "",
    model: "gemini-2.0-flash",
    url: "https://app.aptlyflow.xyz",
    test_instruction: "",
    auth_enabled: false,
    auth_email: "",
    auth_password: "",
    max_tokens: 4096,
    temperature: 0.3,
    mode: "stealth",
    browser: "chromium",
    max_steps: 200,
    screenshot_on_error: true,
    screenshot_on_action: true,
    dom_exploration_enabled: true,
    hidden_menu_expander: true,
    deep_traversal: true,
    path_discovery_boost: 1,
    form_validation_pass: true,
    email_verification_enabled: false,
    email_provider: "1secmail",
    email_provider_base_url: "https://www.1secmail.com/api/v1/",
    email_poll_timeout_seconds: 120,
    email_poll_interval_seconds: 5,
  });

  const isRunning =
    testStatus.status === "running" || testStatus.status === "pending";
  const canStart = !!form.api_key && !!form.model && !!form.url;

  const statusVariant = useMemo(() => {
    if (testStatus.status === "completed") return "success";
    if (testStatus.status === "failed") return "destructive";
    if (testStatus.status === "running") return "warning";
    return "secondary";
  }, [testStatus.status]);

  const latestReport = useMemo(() => reports[0] ?? null, [reports]);

  async function loadReports() {
    const response = await fetch("/api/reports");
    const data = await response.json();
    setReports(data.reports || []);
  }

  async function loadModels() {
    const query = form.api_key
      ? `?api_key=${encodeURIComponent(form.api_key)}`
      : "";
    try {
      const response = await fetch(`/api/models/${GEMINI_PROVIDER}${query}`);
      const data = await response.json();
      const nextModels = data.models?.length ? data.models : GEMINI_MODELS;
      setModels(nextModels);
      setForm((prev) => {
        const stillValid = nextModels.some(
          (m: { id: string }) => m.id === prev.model,
        );
        if (stillValid) return prev;
        return {
          ...prev,
          model: data.default_model || nextModels[0]?.id || "gemini-2.0-flash",
        };
      });
    } catch {
      // keep static list on network error
    }
  }

  useEffect(() => {
    async function fetchReports() {
      await loadReports();
    }
    fetchReports();
  }, []);

  useEffect(() => {
    // Dynamically fetch Gemini models when the API key is available
    if (form.api_key) {
      (async () => {
        await loadModels();
      })();
    }
  }, [form.api_key]);

  // Auto-scroll AI conversation to bottom on new turns
  useEffect(() => {
    if (activeTab === "ai" && aiScrollRef.current) {
      aiScrollRef.current.scrollTop = aiScrollRef.current.scrollHeight;
    }
  }, [llmTurns, activeTab]);

  useEffect(() => {
    if (!sessionId) return;
    let disposed = false;
    let ws: WebSocket | null = null;
    let retryDelay = 1000;
    const MAX_RETRY = 15000;

    function connect() {
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(
        `${protocol}://${window.location.host}/ws/${sessionId}`,
      );

      ws.onopen = () => {
        retryDelay = 1000; // reset backoff on success
      };

      ws.onmessage = (event) => {
        const data: TestStatus = JSON.parse(event.data);
        setTestStatus(data);
        setLogs((prev) => {
          const existingKeys = new Set(
            prev.map((log) => `${log.ts}-${log.message}`),
          );
          const merged = [...prev];
          for (const log of data.logs || []) {
            const key = `${log.ts}-${log.message}`;
            if (!existingKeys.has(key)) {
              merged.push(log);
              existingKeys.add(key);
            }
          }
          return merged.slice(-250);
        });
        setLlmTurns((prev) => {
          const existingKeys = new Set(
            prev.map((t) => `${t.ts}-${t.agent}-${t.prompt.slice(0, 20)}`),
          );
          const merged = [...prev];
          for (const turn of data.llm_turns || []) {
            const key = `${turn.ts}-${turn.agent}-${turn.prompt.slice(0, 20)}`;
            if (!existingKeys.has(key)) {
              merged.push(turn);
              existingKeys.add(key);
            }
          }
          return merged.slice(-100);
        });
        if (data.status === "completed" || data.status === "failed") {
          void loadReports();
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        // Auto-reconnect with exponential backoff
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 1.5, MAX_RETRY);
      };

      ws.onerror = () => {
        // onclose will fire after onerror, triggering reconnect
      };
    }

    connect();
    return () => {
      disposed = true;
      ws?.close();
    };
  }, [sessionId]);

  async function startTest() {
    if (!canStart) return;
    setLogs([
      {
        level: "info",
        message: "Preparing test session...",
        ts: new Date().toISOString(),
      },
    ]);
    setLlmTurns([]);
    const payload = {
      provider: GEMINI_PROVIDER,
      ...form,
      headless: form.mode === "stealth",
      output_dir: "./reports",
    };
    const response = await fetch("/api/test/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      alert(data.error || "Failed to start test");
      return;
    }
    setSessionId(data.session_id);
    setSteerInstruction(form.test_instruction || "");
    setTestStatus((prev) => ({ ...prev, status: "running" }));
  }

  async function stopTest() {
    if (!sessionId) return;
    await fetch(`/api/test/${sessionId}/stop`, { method: "POST" });
  }

  async function steerRunningTest() {
    if (!sessionId || !steerInstruction.trim()) return;
    const response = await fetch(`/api/test/${sessionId}/directive`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: steerInstruction.trim() }),
    });
    const data = await response.json();
    if (!response.ok) {
      alert(data.error || "Failed to send directive");
      return;
    }
    setLogs((prev) => [
      ...prev,
      {
        level: "info",
        message: `Directive updated: ${steerInstruction.trim()}`,
        ts: new Date().toISOString(),
      },
    ]);
  }

  const update = (key: keyof typeof form, value: string | number | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 via-indigo-50 to-cyan-50 p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex items-center justify-between rounded-xl border bg-white/80 p-5 shadow-sm backdrop-blur">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              ✨ WebQA Plus — Powered by Gemini
            </h1>
            <p className="text-sm text-muted-foreground">
              Multimodal AI visual QA tester &bull; Google Gemini Live Agent
              Challenge
            </p>
          </div>
          <div className="flex items-center gap-2">
            {latestReport ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  window.open(
                    `/api/reports/${encodeURIComponent(latestReport.filename)}`,
                    "_blank",
                  )
                }
              >
                Open Report
              </Button>
            ) : null}
            <Badge
              variant={
                statusVariant as
                  | "success"
                  | "destructive"
                  | "warning"
                  | "secondary"
              }
            >
              {testStatus.status.toUpperCase()}
            </Badge>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bot className="h-4 w-4" /> Setup
              </CardTitle>
              <CardDescription>
                Configure provider, credentials, and target
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Gemini Model</Label>
                  <Select
                    value={form.model}
                    onChange={(e) => update("model", e.target.value)}
                  >
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Google API Key</Label>
                  <Input
                    type="password"
                    placeholder="AIza..."
                    value={form.api_key}
                    onChange={(e) => update("api_key", e.target.value)}
                    onBlur={() => void loadModels()}
                  />
                  <p className="text-xs text-muted-foreground">
                    Get yours free at{" "}
                    <a
                      href="https://aistudio.google.com/apikey"
                      target="_blank"
                      rel="noreferrer"
                      className="underline"
                    >
                      aistudio.google.com
                    </a>
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <Label>Target URL</Label>
                <Input
                  value={form.url}
                  onChange={(e) => update("url", e.target.value)}
                  placeholder="https://example.com"
                />
              </div>

              <div className="space-y-2">
                <Label>What should be tested?</Label>
                <Input
                  value={form.test_instruction}
                  onChange={(e) => update("test_instruction", e.target.value)}
                  placeholder="e.g. Test signup + forgot password and verify validation errors"
                />
                <p className="text-xs text-muted-foreground">
                  This directs agent priorities during exploration and testing.
                </p>
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Mode</Label>
                  <Select
                    value={form.mode}
                    onChange={(e) => update("mode", e.target.value)}
                  >
                    <option value="stealth">Stealth</option>
                    <option value="visual">Visual</option>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Browser</Label>
                  <Select
                    value={form.browser}
                    onChange={(e) => update("browser", e.target.value)}
                  >
                    <option value="chromium">Chromium</option>
                    <option value="firefox">Firefox</option>
                    <option value="webkit">WebKit</option>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Max Steps</Label>
                  <Input
                    type="number"
                    value={form.max_steps}
                    onChange={(e) =>
                      update("max_steps", Number(e.target.value))
                    }
                  />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Switch
                  checked={form.auth_enabled}
                  onCheckedChange={(checked) => update("auth_enabled", checked)}
                />
                <Label className="flex items-center gap-1">
                  <Shield className="h-4 w-4" /> Enable auth form credentials
                </Label>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.dom_exploration_enabled}
                    onCheckedChange={(checked) =>
                      update("dom_exploration_enabled", checked)
                    }
                  />
                  <Label>Enable DOM-based exploration</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.hidden_menu_expander}
                    onCheckedChange={(checked) =>
                      update("hidden_menu_expander", checked)
                    }
                  />
                  <Label>Run hidden-menu expander pass</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.deep_traversal}
                    onCheckedChange={(checked) =>
                      update("deep_traversal", checked)
                    }
                  />
                  <Label>Enable deep intent traversal</Label>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.form_validation_pass}
                    onCheckedChange={(checked) =>
                      update("form_validation_pass", checked)
                    }
                  />
                  <Label>Run form validation pass</Label>
                </div>
                <div className="space-y-2">
                  <Label>Path Discovery Boost (0-5)</Label>
                  <Input
                    type="number"
                    min={0}
                    max={5}
                    value={form.path_discovery_boost}
                    onChange={(e) =>
                      update(
                        "path_discovery_boost",
                        Math.min(5, Math.max(0, Number(e.target.value) || 0)),
                      )
                    }
                  />
                </div>
                <div className="flex items-center gap-2 md:col-span-2">
                  <Switch
                    checked={form.email_verification_enabled}
                    onCheckedChange={(checked) =>
                      update("email_verification_enabled", checked)
                    }
                  />
                  <Label>
                    Enable dynamic email verification for signup/forgot flows
                  </Label>
                </div>
                {form.email_verification_enabled && (
                  <>
                    <div className="space-y-2">
                      <Label>Email Provider</Label>
                      <Input
                        value={form.email_provider}
                        onChange={(e) =>
                          update("email_provider", e.target.value)
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Email Provider Base URL</Label>
                      <Input
                        value={form.email_provider_base_url}
                        onChange={(e) =>
                          update("email_provider_base_url", e.target.value)
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Email Poll Timeout (seconds)</Label>
                      <Input
                        type="number"
                        min={15}
                        value={form.email_poll_timeout_seconds}
                        onChange={(e) =>
                          update(
                            "email_poll_timeout_seconds",
                            Math.max(15, Number(e.target.value) || 15),
                          )
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Email Poll Interval (seconds)</Label>
                      <Input
                        type="number"
                        min={2}
                        value={form.email_poll_interval_seconds}
                        onChange={(e) =>
                          update(
                            "email_poll_interval_seconds",
                            Math.max(2, Number(e.target.value) || 2),
                          )
                        }
                      />
                    </div>
                  </>
                )}
              </div>

              {form.auth_enabled && (
                <div className="grid gap-4 md:grid-cols-2">
                  <Input
                    placeholder="Auth email"
                    value={form.auth_email}
                    onChange={(e) => update("auth_email", e.target.value)}
                  />
                  <Input
                    type="password"
                    placeholder="Auth password"
                    value={form.auth_password}
                    onChange={(e) => update("auth_password", e.target.value)}
                  />
                </div>
              )}

              <div className="flex gap-2">
                <Button onClick={startTest} disabled={!canStart || isRunning}>
                  <Play className="h-4 w-4" /> Start Test
                </Button>
                <Button
                  variant="destructive"
                  onClick={stopTest}
                  disabled={!isRunning}
                >
                  <Square className="h-4 w-4" /> Stop
                </Button>
                <Button
                  variant="secondary"
                  onClick={startTest}
                  disabled={!canStart || isRunning}
                >
                  <RefreshCw className="h-4 w-4" /> Re-run
                </Button>
              </div>

              <div className="grid gap-2 md:grid-cols-[1fr_auto]">
                <Input
                  value={steerInstruction}
                  onChange={(e) => setSteerInstruction(e.target.value)}
                  placeholder="While running: steer the test (e.g. verify booking flow errors)"
                />
                <Button
                  variant="outline"
                  disabled={!isRunning || !steerInstruction.trim()}
                  onClick={steerRunningTest}
                >
                  Update Directive
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-4 w-4" /> Progress
              </CardTitle>
              <CardDescription>Live session monitoring</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Progress value={testStatus.progress || 0} />
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-md border p-2">
                  Steps: <b>{testStatus.current_step}</b>
                </div>
                <div className="rounded-md border p-2">
                  URLs: <b>{testStatus.urls_visited}</b>
                </div>
                <div className="rounded-md border p-2">
                  Flows: <b>{testStatus.flows_discovered}</b>
                </div>
                <div className="rounded-md border p-2">
                  Results: <b>{testStatus.test_results}</b>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex gap-1">
                <button
                  className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                    activeTab === "logs"
                      ? "bg-slate-900 text-white"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  onClick={() => setActiveTab("logs")}
                >
                  <Activity className="h-3.5 w-3.5" /> Activity Log
                </button>
                <button
                  className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                    activeTab === "ai"
                      ? "bg-indigo-600 text-white"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  onClick={() => setActiveTab("ai")}
                >
                  <Eye className="h-3.5 w-3.5" /> Gemini Vision
                  {llmTurns.length > 0 && (
                    <span className="ml-1 rounded-full bg-indigo-500/30 px-1.5 text-xs">
                      {llmTurns.length}
                    </span>
                  )}
                  {isRunning && llmTurns.length > 0 && (
                    <span className="ml-1 relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                    </span>
                  )}
                </button>
                <button
                  className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                    activeTab === "memory"
                      ? "bg-amber-600 text-white"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                  onClick={() => setActiveTab("memory")}
                >
                  <Brain className="h-3.5 w-3.5" /> Agent Memory
                  {(testStatus.learning_memory?.length ?? 0) > 0 && (
                    <span className="ml-1 rounded-full bg-amber-500/30 px-1.5 text-xs">
                      {testStatus.learning_memory!.length}
                    </span>
                  )}
                </button>
              </div>
            </CardHeader>
            <CardContent>
              {activeTab === "logs" ? (
                <>
                  <div className="max-h-[300px] space-y-2 overflow-auto rounded-md border bg-slate-950 p-3 font-mono text-xs text-slate-200">
                    {logs.length === 0 ? (
                      <div>No logs yet.</div>
                    ) : (
                      [...logs].reverse().map((log, index) => (
                        <div key={`${log.ts}-${index}`} className="flex gap-2">
                          <span className="text-slate-400">
                            {log.ts
                              ? new Date(log.ts).toLocaleTimeString()
                              : "--:--:--"}
                          </span>
                          <span>{log.message}</span>
                        </div>
                      ))
                    )}
                  </div>
                  {testStatus.errors?.length > 0 && (
                    <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                      {testStatus.errors[0]}
                      {testStatus.debug_errors?.length ? (
                        <pre className="mt-2 whitespace-pre-wrap text-xs">
                          {
                            testStatus.debug_errors[
                              testStatus.debug_errors.length - 1
                            ]
                          }
                        </pre>
                      ) : null}
                    </div>
                  )}
                </>
              ) : activeTab === "ai" ? (
                <div className="space-y-2">
                  {/* Agent filter bar */}
                  <div className="flex gap-1 flex-wrap">
                    {[
                      "all",
                      "vision-analyze",
                      "explorer",
                      "tester",
                      "tester/vision",
                      "tester/ocr",
                      "validator",
                    ].map((filter) => (
                      <button
                        key={filter}
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium border transition-colors ${
                          aiFilter === filter
                            ? "bg-indigo-600 text-white border-indigo-600"
                            : "bg-white text-slate-600 border-slate-200 hover:border-indigo-300"
                        }`}
                        onClick={() => setAiFilter(filter)}
                      >
                        {filter === "all"
                          ? "All"
                          : filter === "vision-analyze"
                            ? "👁 Vision"
                            : filter}
                      </button>
                    ))}
                  </div>

                  <div
                    ref={aiScrollRef}
                    className="max-h-[420px] space-y-3 overflow-auto scroll-smooth"
                  >
                    {llmTurns.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-10 text-center">
                        <Eye className="h-10 w-10 text-indigo-200 mb-3" />
                        <p className="text-sm text-muted-foreground">
                          No AI conversations yet. Start a test to see live
                          Gemini vision analysis and agent reasoning.
                        </p>
                      </div>
                    ) : (
                      (() => {
                        const agentColors: Record<string, string> = {
                          explorer:
                            "bg-indigo-50 text-indigo-700 border-indigo-200",
                          tester:
                            "bg-emerald-50 text-emerald-700 border-emerald-200",
                          "tester/ocr":
                            "bg-amber-50 text-amber-700 border-amber-200",
                          "tester/vision":
                            "bg-sky-50 text-sky-700 border-sky-200",
                          "tester/vision-analyze":
                            "bg-violet-50 text-violet-700 border-violet-200",
                          "tester/visual":
                            "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
                          validator: "bg-rose-50 text-rose-700 border-rose-200",
                        };
                        const agentIcons: Record<string, string> = {
                          explorer: "🔍",
                          tester: "🧪",
                          "tester/ocr": "📝",
                          "tester/vision": "👁",
                          "tester/vision-analyze": "🔬",
                          "tester/visual": "🎯",
                          validator: "✅",
                        };

                        const filtered =
                          aiFilter === "all"
                            ? llmTurns
                            : aiFilter === "vision-analyze"
                              ? llmTurns.filter(
                                  (t) =>
                                    t.agent === "tester/vision-analyze" ||
                                    t.agent === "tester/vision",
                                )
                              : llmTurns.filter((t) => t.agent === aiFilter);

                        return filtered.map((turn, index) => {
                          const badgeClass =
                            agentColors[turn.agent] ??
                            "bg-slate-50 text-slate-600 border-slate-200";
                          const icon = agentIcons[turn.agent] ?? "🤖";
                          const isExpanded = expandedTurns.has(index);
                          const promptPreview =
                            turn.prompt.length > 200 && !isExpanded
                              ? turn.prompt.slice(0, 200) + "…"
                              : turn.prompt;
                          const responsePreview =
                            turn.response.length > 300 && !isExpanded
                              ? turn.response.slice(0, 300) + "…"
                              : turn.response;
                          const canExpand =
                            turn.prompt.length > 200 ||
                            turn.response.length > 300;

                          return (
                            <div
                              key={`${turn.ts}-${index}`}
                              className={`rounded-lg border p-3 shadow-sm space-y-2 transition-all ${
                                turn.agent === "tester/vision-analyze"
                                  ? "border-violet-200 bg-violet-50/30"
                                  : "bg-white"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                  <span className="text-base">{icon}</span>
                                  <span
                                    className={`rounded-full border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${badgeClass}`}
                                  >
                                    {turn.agent === "tester/vision-analyze"
                                      ? "Vision Analysis"
                                      : turn.agent}
                                  </span>
                                </div>
                                <span className="text-xs text-muted-foreground">
                                  {turn.ts
                                    ? new Date(turn.ts).toLocaleTimeString()
                                    : ""}
                                </span>
                              </div>
                              {/* Agent prompt */}
                              <div className="rounded-md bg-slate-900 p-2 font-mono text-xs text-slate-200">
                                <span className="text-slate-500 mr-1 select-none">
                                  →
                                </span>
                                <span className="whitespace-pre-wrap break-all">
                                  {promptPreview}
                                </span>
                              </div>
                              {/* Gemini response */}
                              <div className="rounded-md bg-indigo-950 p-2 font-mono text-xs text-indigo-100">
                                <span className="text-indigo-400 mr-1 select-none">
                                  ←
                                </span>
                                <span className="whitespace-pre-wrap break-all">
                                  {responsePreview}
                                </span>
                              </div>
                              {canExpand && (
                                <button
                                  className="text-xs text-indigo-500 hover:text-indigo-700 font-medium"
                                  onClick={() =>
                                    setExpandedTurns((prev) => {
                                      const next = new Set(prev);
                                      if (next.has(index)) next.delete(index);
                                      else next.add(index);
                                      return next;
                                    })
                                  }
                                >
                                  {isExpanded
                                    ? "Show less"
                                    : "Show full conversation"}
                                </button>
                              )}
                            </div>
                          );
                        });
                      })()
                    )}
                    {isRunning && llmTurns.length > 0 && (
                      <div className="flex items-center gap-2 py-2 px-3 rounded-md bg-indigo-50 border border-indigo-100 text-xs text-indigo-600">
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                        </span>
                        Gemini is analyzing the page…
                      </div>
                    )}
                  </div>
                </div>
              ) : activeTab === "memory" ? (
                <div className="max-h-[420px] space-y-2 overflow-auto">
                  {(testStatus.learning_memory?.length ?? 0) === 0 ? (
                    <div className="flex flex-col items-center justify-center py-10 text-center">
                      <Brain className="h-10 w-10 text-amber-200 mb-3" />
                      <p className="text-sm text-muted-foreground">
                        No learnings yet. The agent accumulates insights as it
                        interacts with the app during testing.
                      </p>
                    </div>
                  ) : (
                    [...(testStatus.learning_memory ?? [])]
                      .reverse()
                      .map((insight, i) => (
                        <div
                          key={i}
                          className="rounded-md border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900"
                        >
                          <span className="mr-1.5 font-semibold text-amber-600">
                            #{testStatus.learning_memory!.length - i}
                          </span>
                          {insight}
                        </div>
                      ))
                  )}
                  {isRunning &&
                    (testStatus.learning_memory?.length ?? 0) > 0 && (
                      <div className="flex items-center gap-2 py-2 px-3 rounded-md bg-amber-50 border border-amber-100 text-xs text-amber-600">
                        <span className="relative flex h-2 w-2">
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                          <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                        </span>
                        Agent is learning from interactions…
                      </div>
                    )}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <FileText className="h-4 w-4" /> Reports
                </span>
                {latestReport ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      window.open(
                        `/api/reports/${encodeURIComponent(latestReport.filename)}`,
                        "_blank",
                      )
                    }
                  >
                    Latest
                  </Button>
                ) : null}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {reports.length === 0 ? (
                <p className="text-sm text-muted-foreground">No reports yet.</p>
              ) : (
                reports.map((report) => (
                  <div
                    key={report.filename}
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <div>
                      <div className="text-sm font-medium">
                        {report.filename}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {new Date(report.created).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          window.open(
                            `/api/reports/${encodeURIComponent(report.filename)}`,
                            "_blank",
                          )
                        }
                      >
                        View
                      </Button>
                      <Button
                        size="sm"
                        onClick={() =>
                          (window.location.href = `/api/reports/${encodeURIComponent(report.filename)}?download=true`)
                        }
                      >
                        Download
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Globe className="h-3 w-3" />
          Hot-reload enabled via Vite dev server. Save any React file and UI
          updates instantly.
        </div>
      </div>
    </div>
  );
}

export default App;

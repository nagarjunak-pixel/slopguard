import { useEffect, useState } from "react";

interface SlopFinding {
  rule_id: string;
  severity: string;
  weight: number;
  file_path: string;
  line: number;
  message: string;
  remediation: string;
  snippet: string;
}

interface SlopReport {
  kernel_backend: string;
  verdict: string;
  risk_score: number;
  total_lines: number;
  files_scanned: number;
  blocker_count: number;
  warning_count: number;
  scan_duration_ms: number;
  rule_counts: Record<string, number>;
  findings: SlopFinding[];
}

interface DemoPayload {
  sloppy_python: string;
  clean_python: string;
  sloppy_tsx: string;
  clean_tsx: string;
  sloppy_py_report: SlopReport;
  clean_py_report: SlopReport;
  sloppy_tsx_report: SlopReport;
  clean_tsx_report: SlopReport;
  claude_hook_exit_code: number;
  claude_hook_decision: string;
  claude_hook_reason: string;
}

interface BenchmarkTask {
  task_id: string;
  title: string;
  language: string;
  v1_verdict: string;
  v1_blockers: number;
  v1_risk_score: number;
  v2_verdict: string;
  v2_blockers: number;
  v2_risk_score: number;
  v2_syntax_valid: boolean;
  repair_latency_ms: number;
}

interface AuditReport {
  model: string;
  execution_mode: string;
  total_tasks: number;
  v1_pass_rate_pct: number;
  v2_pass_rate_pct: number;
  total_blockers_eliminated: number;
  avg_repair_latency_ms: number;
  tasks: BenchmarkTask[];
}

interface HealthInfo {
  status: string;
  service: string;
  version: string;
  kernel_backend: string;
}

type PresetKey = "sloppy_py" | "clean_py" | "sloppy_tsx" | "clean_tsx";

const HOOK_SNIPPET = `{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --directory /path/to/slopguard slopguard claude-hook"
          }
        ]
      }
    ]
  }
}`;

export default function App() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [demo, setDemo] = useState<DemoPayload | null>(null);
  const [audit, setAudit] = useState<AuditReport | null>(null);
  const [preset, setPreset] = useState<PresetKey>("sloppy_py");
  const [liveReport, setLiveReport] = useState<SlopReport | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/v1/health").then((r) => r.json()),
      fetch("/api/v1/demo").then((r) => r.json()),
      fetch("/api/v1/audit/ollama").then((r) => r.json()),
    ])
      .then(([h, d, a]) => {
        setHealth(h);
        setDemo(d);
        setLiveReport(d.sloppy_py_report);
        setAudit(a);
      })
      .catch(() => {
        // Empty state handled cleanly
      });
  }, []);

  const selectPreset = async (next: PresetKey) => {
    if (!demo) return;
    setPreset(next);
    const map: Record<PresetKey, { code: string; path: string }> = {
      sloppy_py: { code: demo.sloppy_python, path: "src/payouts.py" },
      clean_py: { code: demo.clean_python, path: "src/payouts.py" },
      sloppy_tsx: { code: demo.sloppy_tsx, path: "ui/BillingCard.tsx" },
      clean_tsx: { code: demo.clean_tsx, path: "ui/BillingCard.tsx" },
    };
    const item = map[next];
    const resp = await fetch("/api/v1/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: item.code, file_path: item.path }),
    });
    const rep: SlopReport = await resp.json();
    setLiveReport(rep);
  };

  if (!demo || !liveReport) {
    return (
      <div className="page">
        <p className="subtitle">Loading slopguard C++20 & AST Audit Console...</p>
      </div>
    );
  }

  const activeSource =
    preset === "sloppy_py"
      ? demo.sloppy_python
      : preset === "clean_py"
        ? demo.clean_python
        : preset === "sloppy_tsx"
          ? demo.sloppy_tsx
          : demo.clean_tsx;

  return (
    <div className="page">
      <header className="header">
        <div>
          <h1 className="title">slopguard — Sub-Second AI Code &amp; UI Anti-Slop Verifier</h1>
          <p className="subtitle">
            Native C++20 Byte Prescreener · Python AST Import/Stub/Test Verifier · Claude Code Hooks
            · MCP Server
          </p>
        </div>
        <div className="badges">
          <span className="badge">v{health?.version ?? "1.0.0"}</span>
          <span className="badge emerald">
            {health?.kernel_backend ?? liveReport.kernel_backend}
          </span>
          <span className="badge">Claude Hook exit={demo.claude_hook_exit_code}</span>
          {audit && (
            <span className="badge emerald">
              {audit.model} ({audit.execution_mode})
            </span>
          )}
        </div>
      </header>

      <section className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-label">Active Gate Verdict</div>
          <div className={`kpi-value ${liveReport.verdict === "BLOCK" ? "rose" : ""}`}>
            {liveReport.verdict}
          </div>
          <div className="kpi-sub">
            Risk {liveReport.risk_score}/100 · {liveReport.blocker_count} blockers,{" "}
            {liveReport.warning_count} warnings
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Scan Latency</div>
          <div className="kpi-value">{liveReport.scan_duration_ms.toFixed(2)} ms</div>
          <div className="kpi-sub">{liveReport.total_lines} lines verified in-process</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Live {audit?.model ?? "Qwen"} Repair Pass</div>
          <div className="kpi-value">
            {audit
              ? `${audit.v1_pass_rate_pct.toFixed(0)}% → ${audit.v2_pass_rate_pct.toFixed(0)}%`
              : "—"}
          </div>
          <div className="kpi-sub">
            {audit
              ? `${audit.total_blockers_eliminated} blockers eliminated across ${audit.total_tasks} tasks`
              : "Run eval-ollama"}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Claude Code Hook Gate</div>
          <div className="kpi-value rose">{demo.claude_hook_decision.toUpperCase()}</div>
          <div className="kpi-sub">Auto-rejects unverified stubs &amp; fake imports on Write</div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2 className="panel-title">Interactive Anti-Slop Code &amp; UI Inspector</h2>
          <div className="controls">
            <button
              className={`btn ${preset === "sloppy_py" ? "active" : "secondary"}`}
              onClick={() => void selectPreset("sloppy_py")}
            >
              Sloppy Python
            </button>
            <button
              className={`btn ${preset === "clean_py" ? "active" : "secondary"}`}
              onClick={() => void selectPreset("clean_py")}
            >
              Clean Python
            </button>
            <button
              className={`btn ${preset === "sloppy_tsx" ? "active" : "secondary"}`}
              onClick={() => void selectPreset("sloppy_tsx")}
            >
              Sloppy React TSX
            </button>
            <button
              className={`btn ${preset === "clean_tsx" ? "active" : "secondary"}`}
              onClick={() => void selectPreset("clean_tsx")}
            >
              Clean React TSX
            </button>
          </div>
        </div>

        <div className="split">
          <div>
            <div className="code-label">
              <span>Inspected Source Code</span>
              <span>{liveReport.total_lines} lines</span>
            </div>
            <pre className="code-box">{activeSource}</pre>
          </div>
          <div>
            <div className="code-label">
              <span>Diagnostics ({liveReport.findings.length} findings)</span>
              <span>Verdict: {liveReport.verdict}</span>
            </div>
            {liveReport.findings.length === 0 ? (
              <div className="code-box">
                PASS (Risk 0/100) — Zero hallucinated imports, dead stubs, silent exceptions, or
                fake assertions detected.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Rule</th>
                    <th>Severity</th>
                    <th>Diagnostic</th>
                  </tr>
                </thead>
                <tbody>
                  {liveReport.findings.map((f, idx) => (
                    <tr key={`${f.rule_id}-${f.line}-${idx}`}>
                      <td>L{f.line}</td>
                      <td>{f.rule_id}</td>
                      <td>
                        <span className={f.severity === "BLOCKER" ? "pill-block" : "pill-warn"}>
                          {f.severity}
                        </span>
                      </td>
                      <td>{f.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </section>

      <div className="split">
        {audit && (
          <section className="panel">
            <div className="panel-head">
              <h2 className="panel-title">
                Live {audit.model} Guided Anti-Slop Repair ({audit.total_tasks} Tasks)
              </h2>
              <span className="pill-pass">
                v1 {audit.v1_pass_rate_pct.toFixed(0)}% → v2 {audit.v2_pass_rate_pct.toFixed(0)}%
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>v1 Slop</th>
                  <th>v2 Guarded</th>
                  <th>AST</th>
                </tr>
              </thead>
              <tbody>
                {audit.tasks.map((t) => (
                  <tr key={t.task_id}>
                    <td>
                      <strong>{t.task_id}</strong> · {t.title}
                    </td>
                    <td>
                      <span className="pill-block">
                        {t.v1_verdict} ({t.v1_blockers})
                      </span>
                    </td>
                    <td>
                      <span className={t.v2_verdict === "PASS" ? "pill-pass" : "pill-warn"}>
                        {t.v2_verdict} ({t.v2_blockers})
                      </span>
                    </td>
                    <td>{t.v2_syntax_valid ? "Valid" : "Invalid"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="panel">
          <div className="panel-head">
            <h2 className="panel-title">Claude Code Hook (`PostToolUse`) Integration</h2>
            <span className="pill-warn">Blocks Bad Edits Automatically</span>
          </div>
          <pre className="code-box">{HOOK_SNIPPET}</pre>
        </section>
      </div>
    </div>
  );
}

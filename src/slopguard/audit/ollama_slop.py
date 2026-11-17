"""Live Ollama (`qwen3.5:4b`) benchmark testing unguarded v1 AI slop vs slopguard-guided v2 repair."""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from slopguard.analyzers.gate_engine import scan_source
from slopguard.types import GateVerdict, RealSlopAuditReport, SlopBenchmarkTask


def default_slop_audit_path() -> Path:
    return Path(__file__).resolve().parents[3] / "benchmarks" / "real_qwen_slopguard.json"


@dataclass(frozen=True)
class _SlopSpec:
    task_id: str
    title: str
    language: str
    file_path: str
    slop_code: str
    extra_guidance: str


def _build_specs() -> list[_SlopSpec]:
    return [
        _SlopSpec(
            task_id="SG-01",
            title="Hallucinated Import + Empty JWT Verify Stub",
            language="python",
            file_path="src/auth_token.py",
            slop_code=(
                "from fastapi_quantum_shield import verify_jwt_token\n\n"
                "def check_bearer(secret: str, message: str, sig_hex: str) -> bool:\n"
                "    ...\n"
            ),
            extra_guidance=(
                "Replace the fake import with Python stdlib `hmac` and `hashlib`, "
                "and implement real constant-time HMAC-SHA256 verification."
            ),
        ),
        _SlopSpec(
            task_id="SG-02",
            title="Silent Exception Swallow + Empty Ledger Return Stub",
            language="python",
            file_path="src/ledger_sync.py",
            slop_code=(
                "def summarize_entries(entries: list[int]) -> dict[str, int]:\n"
                "    return {}\n\n"
                "def parse_amount(raw: str) -> int:\n"
                "    try:\n"
                "        return int(raw)\n"
                "    except Exception:\n"
                "        pass\n"
            ),
            extra_guidance=(
                "Implement summarize_entries returning {'count': len(entries), 'total': sum(entries)}, "
                "and in parse_amount raise ValueError explicitly with context instead of pass."
            ),
        ),
        _SlopSpec(
            task_id="SG-03",
            title="Tautological Pytest Function (assert True)",
            language="python",
            file_path="tests/test_checkout.py",
            slop_code=("def test_checkout_total() -> None:\n    assert True\n"),
            extra_guidance=(
                "Implement a real test computing subtotal=3 * 250 plus tax=75 and asserting exact equality."
            ),
        ),
        _SlopSpec(
            task_id="SG-04",
            title="Dead React Button onClick={() => {}} + Coming Soon Copy",
            language="tsx",
            file_path="ui/SyncButton.tsx",
            slop_code=(
                'import React from "react";\n'
                "export function SyncButton() {\n"
                "  return (\n"
                "    <div>\n"
                "      <span>Coming soon placeholder</span>\n"
                "      <button onClick={() => {}}>Sync Now</button>\n"
                "    </div>\n"
                "  );\n"
                "}\n"
            ),
            extra_guidance=(
                "Use React useState count state so clicking the button increments count and displays 'Synced runs: {count}' without placeholder text."
            ),
        ),
        _SlopSpec(
            task_id="SG-05",
            title="Unsafe eval() Sink + NotImplementedError Export Stub",
            language="python",
            file_path="src/csv_export.py",
            slop_code=(
                "def eval_number(text: str) -> int:\n"
                "    return int(eval(text))\n\n"
                "def export_rows(rows: list[tuple[str, int]]) -> str:\n"
                '    raise NotImplementedError("TODO implement CSV export")\n'
            ),
            extra_guidance=(
                "Use ast.literal_eval (or int(text.strip())) in eval_number, and use io.StringIO + csv.writer in export_rows using only Python stdlib."
            ),
        ),
        _SlopSpec(
            task_id="SG-06",
            title="TypeScript Expect(true).toBe(true) + Stub Comment",
            language="typescript",
            file_path="tests/coupon.test.ts",
            slop_code=(
                "// stub implementation\n"
                'test("applies coupon discount", () => {\n'
                "  expect(true).toBe(true);\n"
                "});\n"
            ),
            extra_guidance=(
                "Define const applyDiscount = (price: number, pct: number) => Math.round(price * (100 - pct) / 100); and expect(applyDiscount(200, 15)).toBe(170); remove comments."
            ),
        ),
    ]


_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*\s*\n(.*?)```", re.DOTALL)


def extract_code_block(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip() + "\n"
    return text.strip() + "\n"


def _syntax_is_valid(code: str, language: str) -> bool:
    if language == "python":
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False
    return bool(code.strip()) and ("=>" in code or "function " in code or "return " in code)


def _call_ollama_repair(
    base_url: str, model: str, spec: _SlopSpec, diag_lines: str
) -> tuple[str, float]:
    lang_tag = "python" if spec.language == "python" else "tsx"
    prompt = (
        f"File: {spec.file_path}\n"
        f"Broken Code:\n```{lang_tag}\n{spec.slop_code}```\n\n"
        f"slopguard Findings (MUST ALL BE FIXED):\n{diag_lines}\n\n"
        f"Instructions: {spec.extra_guidance}\n"
        f"Return ONLY the complete repaired file inside a single ```{lang_tag} ... ``` code fence. "
        "Do NOT include TODO comments, stub comments, empty handlers, eval(), or assert True."
    )
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 320},
        "messages": [
            {
                "role": "system",
                "content": "You are a strict principal engineer. Output only valid, complete, working code inside one fenced block.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    t0 = time.perf_counter()
    resp = httpx.post(f"{base_url.rstrip('/')}/api/chat", json=payload, timeout=120.0)
    resp.raise_for_status()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    raw = str(resp.json().get("message", {}).get("content", ""))
    return extract_code_block(raw), round(elapsed_ms, 2)


def run_real_slop_ollama_audit(
    *,
    model: str = "qwen3.5:4b",
    base_url: str = "http://127.0.0.1:11434",
    allow_offline_replay: bool = False,
    output_path: Path | None = None,
) -> RealSlopAuditReport:
    """Measure unguarded v1 AI slop vs slopguard-guided v2 repair using live local Ollama."""
    target_path = output_path or default_slop_audit_path()
    specs = _build_specs()

    try:
        tasks: list[SlopBenchmarkTask] = []
        for spec in specs:
            v1_rep = scan_source(spec.slop_code, file_path=spec.file_path)
            diag_lines = "\n".join(
                f"- [{f.rule_id}] line {f.line}: {f.message} (Fix: {f.remediation})"
                for f in v1_rep.findings
            )
            repaired_code, repair_ms = _call_ollama_repair(base_url, model, spec, diag_lines)
            v2_rep = scan_source(repaired_code, file_path=spec.file_path)
            v2_syntax_ok = _syntax_is_valid(repaired_code, spec.language)
            tasks.append(
                SlopBenchmarkTask(
                    task_id=spec.task_id,
                    title=spec.title,
                    language=spec.language,
                    v1_verdict=v1_rep.verdict,
                    v1_blockers=v1_rep.blocker_count,
                    v1_risk_score=v1_rep.risk_score,
                    v2_verdict=v2_rep.verdict,
                    v2_blockers=v2_rep.blocker_count,
                    v2_risk_score=v2_rep.risk_score,
                    v2_syntax_valid=v2_syntax_ok,
                    repair_latency_ms=repair_ms,
                    v1_code=spec.slop_code,
                    v2_code=repaired_code,
                )
            )
        execution_mode = "live-ollama"
    except Exception:
        if not allow_offline_replay or not target_path.exists():
            raise
        cached = RealSlopAuditReport.model_validate_json(target_path.read_text(encoding="utf-8"))
        cached.execution_mode = "recorded-artifact-replay"
        return cached

    n = len(tasks)
    v1_pass = sum(1 for t in tasks if t.v1_verdict == GateVerdict.PASS)
    v2_pass = sum(1 for t in tasks if t.v2_verdict == GateVerdict.PASS and t.v2_syntax_valid)
    elim = sum(max(0, t.v1_blockers - t.v2_blockers) for t in tasks)
    avg_ms = round(sum(t.repair_latency_ms for t in tasks) / max(1, n), 2)

    report = RealSlopAuditReport(
        model=model,
        execution_mode=execution_mode,
        total_tasks=n,
        v1_pass_rate_pct=round((v1_pass / max(1, n)) * 100.0, 2),
        v2_pass_rate_pct=round((v2_pass / max(1, n)) * 100.0, 2),
        total_blockers_eliminated=elim,
        avg_repair_latency_ms=avg_ms,
        tasks=tasks,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report

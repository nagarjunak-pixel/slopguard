"""Claude Code JSON hook evaluator blocking hallucinated imports, dead stubs, and fake tests on edit."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any

from slopguard.analyzers.gate_engine import discover_known_modules, scan_source
from slopguard.types import GateVerdict


def evaluate_claude_hook_payload(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Inspect a Claude Code Write/Edit hook payload and return (exit_code, response_dict)."""
    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "edit.py")
    content = str(
        tool_input.get("content")
        or tool_input.get("new_string")
        or tool_input.get("new_source")
        or ""
    )
    cwd_raw = payload.get("cwd")
    known = discover_known_modules(Path(str(cwd_raw))) if cwd_raw else set()

    if not content.strip():
        return 0, {"decision": "allow", "reason": "Empty content skipped."}

    report = scan_source(content, file_path=file_path, known_modules=known)
    if report.verdict == GateVerdict.BLOCK:
        top_msgs = "; ".join(f"[{f.rule_id} L{f.line}] {f.message}" for f in report.findings[:4])
        return 2, {
            "decision": "block",
            "reason": f"slopguard blocked {file_path} (risk={report.risk_score}/100, blockers={report.blocker_count}): {top_msgs}",
            "report": report.model_dump(),
        }

    return 0, {
        "decision": "allow",
        "reason": f"slopguard passed {file_path} (verdict={report.verdict.value}, risk={report.risk_score}/100).",
        "report": report.model_dump(),
    }


def run_claude_hook_stdio(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    in_stream = stdin if stdin is not None else sys.stdin
    out_stream = stdout if stdout is not None else sys.stdout
    raw = in_stream.read().strip()
    if not raw:
        out_stream.write(json.dumps({"decision": "allow", "reason": "Empty stdin"}) + "\n")
        return 0
    payload = json.loads(raw)
    code, resp = evaluate_claude_hook_payload(payload)
    out_stream.write(json.dumps(resp) + "\n")
    out_stream.flush()
    return code

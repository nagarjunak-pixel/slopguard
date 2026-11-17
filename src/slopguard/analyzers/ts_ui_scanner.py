"""TypeScript / JSX / text anti-slop analyzer pairing C++20 byte masks with regex precision."""

from __future__ import annotations

import re

from slopguard.kernels.native_scan import scan_bytes
from slopguard.types import Severity, SlopFinding

_EMPTY_HANDLER_RE = re.compile(
    r"\b(?:onClick|onChange|onSubmit|onPress|handle[A-Z]\w*)\s*=\s*\{?\s*\([^)]*\)\s*=>\s*\{\s*\}\s*\}?"
)
_EMPTY_JS_TEST_RE = re.compile(
    r"\b(?:it|test)\s*\(\s*['\"`][^'\"`]+['\"`]\s*,\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)"
)
_PHRASE_PLACEHOLDER_RE = re.compile(
    r"\b(coming soon|lorem ipsum|todo|fixme|placeholder|stub implementation|for brevity|"
    r"dummy return|mock response|in production, replace|simulated only)\b",
    re.IGNORECASE,
)


def inspect_ui_or_text_source(
    source: str, file_path: str = "<input>.tsx"
) -> tuple[list[SlopFinding], int]:
    """Scan TypeScript/JSX or prose/comment slop using C++20 byte scanner + targeted UI patterns."""
    if not source.strip():
        return [], 0

    lines = source.splitlines()
    byte_matches, total_lines = scan_bytes(source.encode("utf-8", errors="ignore"))
    findings: list[SlopFinding] = []
    seen: set[tuple[str, int]] = set()

    def _add(rule_id: str, severity: Severity, weight: int, line: int, msg: str, rem: str) -> None:
        key = (rule_id, line)
        if key in seen:
            return
        seen.add(key)
        snippet = lines[line - 1].strip() if 1 <= line <= len(lines) else ""
        findings.append(
            SlopFinding(
                rule_id=rule_id,
                severity=severity,
                weight=weight,
                file_path=file_path,
                line=line,
                message=msg,
                remediation=rem,
                snippet=snippet,
            )
        )

    for line_no, mask in byte_matches:
        if mask & 8:
            _add(
                "SG007_TAUTOLOGY_JS_ASSERT",
                Severity.BLOCKER,
                35,
                line_no,
                "Tautological test assertion detected (e.g. expect(true).toBe(true) / assert True).",
                "Assert real rendered state, API responses, or exception outcomes.",
            )
        if mask & 16:
            line_low = lines[line_no - 1].lower() if 1 <= line_no <= len(lines) else ""
            if "dangerouslysetinnerhtml" in line_low or "eval(" in line_low:
                _add(
                    "SG008_XSS_UNSAFE_SINK",
                    Severity.BLOCKER,
                    32,
                    line_no,
                    "Unsafe HTML/JS execution sink (dangerouslySetInnerHTML / eval).",
                    "Render safe JSX nodes or sanitize strictly before mounting.",
                )
        if (mask & 1) or (mask & 4):
            _add(
                "SG006_UI_PLACEHOLDER_SLOP",
                Severity.WARN,
                20,
                line_no,
                "AI placeholder / unfinished stub phrase detected in source.",
                "Complete the implementation or replace placeholder copy with live data.",
            )

    for idx, raw_line in enumerate(lines, start=1):
        if _EMPTY_HANDLER_RE.search(raw_line):
            _add(
                "SG006_UI_PLACEHOLDER_SLOP",
                Severity.BLOCKER,
                30,
                idx,
                "Dead no-op UI event handler (e.g. onClick={() => {}}).",
                "Wire the handler to real state updates, API mutation, or remove the control.",
            )
        if _EMPTY_JS_TEST_RE.search(raw_line):
            _add(
                "SG007_TAUTOLOGY_JS_ASSERT",
                Severity.BLOCKER,
                35,
                idx,
                "Empty JS/TS test block with no assertions.",
                "Implement concrete test assertions inside it(...)/test(...).",
            )
        if (
            _PHRASE_PLACEHOLDER_RE.search(raw_line)
            and ("SG006_UI_PLACEHOLDER_SLOP", idx) not in seen
        ):
            _add(
                "SG006_UI_PLACEHOLDER_SLOP",
                Severity.WARN,
                20,
                idx,
                "AI placeholder / TODO comment detected.",
                "Resolve or remove temporary TODO/stub markers.",
            )

    return findings, total_lines

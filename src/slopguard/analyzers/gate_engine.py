"""Unified anti-slop scan engine combining C++20 byte scanner, AST verification & risk gate."""

from __future__ import annotations

import re
import time
from pathlib import Path

from slopguard.analyzers.python_ast import inspect_python_source
from slopguard.analyzers.ts_ui_scanner import inspect_ui_or_text_source
from slopguard.kernels.native_scan import active_backend_name, aggregate_risk, scan_bytes
from slopguard.types import Severity, SlopFinding, SlopReport

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
_SCANNABLE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}


def discover_known_modules(repo_root: Path | None) -> set[str]:
    """Discover local package roots and declared dependencies so valid imports are never flagged."""
    known: set[str] = set()
    if repo_root is None or not repo_root.is_dir():
        return known

    src_dir = repo_root / "src"
    for parent in (repo_root, src_dir):
        if parent.is_dir():
            for child in parent.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    known.add(child.name.replace("-", "_"))
                elif child.is_file() and child.suffix == ".py":
                    known.add(child.stem)

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r'"([A-Za-z0-9_-]+)(?:[><=!~\[;]|")', text):
            known.add(match.replace("-", "_").lower())
            known.add(match.replace("-", "_"))
    return known


def _scan_text_internal(
    source: str,
    file_path: str,
    known_modules: set[str],
    check_text_slop_in_python: bool = True,
) -> tuple[list[SlopFinding], int]:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".py":
        ast_findings = inspect_python_source(
            source, file_path=file_path, known_modules=known_modules
        )
        byte_matches, total_lines = scan_bytes(source.encode("utf-8", errors="ignore"))
        findings = list(ast_findings)
        seen = {(f.rule_id, f.line) for f in findings}
        lines = source.splitlines()
        if check_text_slop_in_python:
            for line_no, mask in byte_matches:
                if (mask & 1 or mask & 4) and not any(f.line == line_no for f in findings):
                    snippet = lines[line_no - 1].strip() if 1 <= line_no <= len(lines) else ""
                    findings.append(
                        SlopFinding(
                            rule_id="SG006_UI_PLACEHOLDER_SLOP",
                            severity=Severity.WARN,
                            weight=15,
                            file_path=file_path,
                            line=line_no,
                            message="Unresolved TODO / stub / placeholder phrase in Python source.",
                            remediation="Finish stub logic or remove placeholder comment before shipping.",
                            snippet=snippet,
                        )
                    )
        for f in findings:
            seen.add((f.rule_id, f.line))
        return findings, total_lines

    return inspect_ui_or_text_source(source, file_path=file_path)


def scan_source(
    source: str,
    file_path: str = "module.py",
    known_modules: set[str] | None = None,
) -> SlopReport:
    """Scan a single source string with sub-millisecond C++20 + AST verification."""
    t0 = time.perf_counter()
    findings, total_lines = _scan_text_internal(source, file_path, known_modules or set())
    weights = [f.weight for f in findings]
    blockers = [1 if f.severity == Severity.BLOCKER else 0 for f in findings]
    verdict, blocker_cnt, risk_score = aggregate_risk(weights, blockers, total_lines)
    warn_cnt = sum(1 for f in findings if f.severity == Severity.WARN)
    rule_counts: dict[str, int] = {}
    for f in findings:
        rule_counts[f.rule_id] = rule_counts.get(f.rule_id, 0) + 1
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return SlopReport(
        kernel_backend=active_backend_name(),
        verdict=verdict,
        risk_score=risk_score,
        total_lines=total_lines,
        files_scanned=1,
        blocker_count=blocker_cnt,
        warning_count=warn_cnt,
        scan_duration_ms=elapsed_ms,
        rule_counts=rule_counts,
        findings=sorted(findings, key=lambda x: (x.file_path, x.line, x.rule_id)),
    )


def scan_directory(root: Path, known_modules: set[str] | None = None) -> SlopReport:
    """Recursively scan a workspace directory respecting standard ignore globs."""
    t0 = time.perf_counter()
    resolved_root = root.resolve()
    modules = discover_known_modules(resolved_root) | (known_modules or set())
    all_findings: list[SlopFinding] = []
    total_lines = 0
    files_scanned = 0

    for path in sorted(resolved_root.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in _SCANNABLE_SUFFIXES:
            continue
        rel = str(path.relative_to(resolved_root))
        text = path.read_text(encoding="utf-8", errors="ignore")
        file_findings, n_lines = _scan_text_internal(text, rel, modules)
        all_findings.extend(file_findings)
        total_lines += n_lines
        files_scanned += 1

    weights = [f.weight for f in all_findings]
    blockers = [1 if f.severity == Severity.BLOCKER else 0 for f in all_findings]
    verdict, blocker_cnt, risk_score = aggregate_risk(weights, blockers, max(1, total_lines))
    warn_cnt = sum(1 for f in all_findings if f.severity == Severity.WARN)
    rule_counts: dict[str, int] = {}
    for f in all_findings:
        rule_counts[f.rule_id] = rule_counts.get(f.rule_id, 0) + 1
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return SlopReport(
        kernel_backend=active_backend_name(),
        verdict=verdict,
        risk_score=risk_score,
        total_lines=total_lines,
        files_scanned=files_scanned,
        blocker_count=blocker_cnt,
        warning_count=warn_cnt,
        scan_duration_ms=elapsed_ms,
        rule_counts=rule_counts,
        findings=all_findings,
    )

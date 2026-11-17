"""Pydantic v2 data contracts for slopguard static verification, Claude hooks, and Ollama audits."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GateVerdict(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class Severity(StrEnum):
    WARN = "WARN"
    BLOCKER = "BLOCKER"


class SlopFinding(BaseModel):
    rule_id: str
    severity: Severity
    weight: int
    file_path: str
    line: int
    message: str
    remediation: str
    snippet: str = ""


class SlopReport(BaseModel):
    kernel_backend: str
    verdict: GateVerdict
    risk_score: int
    total_lines: int
    files_scanned: int
    blocker_count: int
    warning_count: int
    scan_duration_ms: float
    rule_counts: dict[str, int] = Field(default_factory=dict)
    findings: list[SlopFinding] = Field(default_factory=list)


class SlopBenchmarkTask(BaseModel):
    task_id: str
    title: str
    language: str
    v1_verdict: GateVerdict
    v1_blockers: int
    v1_risk_score: int
    v2_verdict: GateVerdict
    v2_blockers: int
    v2_risk_score: int
    v2_syntax_valid: bool
    repair_latency_ms: float
    v1_code: str
    v2_code: str


class RealSlopAuditReport(BaseModel):
    model: str
    execution_mode: str
    total_tasks: int
    v1_pass_rate_pct: float
    v2_pass_rate_pct: float
    total_blockers_eliminated: int
    avg_repair_latency_ms: float
    tasks: list[SlopBenchmarkTask]

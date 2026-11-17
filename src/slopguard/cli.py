"""Rich Typer CLI for slopguard: demo, scan, claude-hook, eval-ollama, mcp-stdio, and serve."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from slopguard.analyzers.gate_engine import scan_directory, scan_source
from slopguard.api.app import create_app
from slopguard.audit.ollama_slop import run_real_slop_ollama_audit
from slopguard.demo import build_demo_showcase
from slopguard.hooks.claude_hook import run_claude_hook_stdio
from slopguard.kernels.native_scan import active_backend_name
from slopguard.mcp.server import SlopGuardMCPServer
from slopguard.types import GateVerdict

app = typer.Typer(
    name="slopguard",
    help="Sub-Second C++20 & AST Anti-Slop Verifier, Claude Code Hook & MCP Server.",
    add_completion=False,
)
console = Console()


@app.command()
def demo() -> None:
    """Compare sloppy AI output against clean verified code and run the Claude Code hook gate."""
    payload = build_demo_showcase()
    console.print(f"[bold cyan]slopguard v1.0.0[/] | Kernel: [green]{active_backend_name()}[/]")

    tbl = Table(title="Anti-Slop Gate & Risk Summary")
    tbl.add_column("Target")
    tbl.add_column("Verdict")
    tbl.add_column("Risk", justify="right")
    tbl.add_column("Blockers", justify="right")
    tbl.add_column("Warnings", justify="right")
    tbl.add_column("Time (ms)", justify="right")

    for name, rep in (
        ("Sloppy Python Handler", payload.sloppy_py_report),
        ("Clean Python Handler", payload.clean_py_report),
        ("Sloppy React/TSX Card", payload.sloppy_tsx_report),
        ("Clean React/TSX Card", payload.clean_tsx_report),
    ):
        tbl.add_row(
            name,
            rep.verdict.value,
            f"{rep.risk_score}/100",
            str(rep.blocker_count),
            str(rep.warning_count),
            f"{rep.scan_duration_ms:.3f}",
        )
    console.print(tbl)
    console.print(
        f"[bold red]Claude Hook Decision:[/] {payload.claude_hook_decision} "
        f"(exit={payload.claude_hook_exit_code}) | {payload.claude_hook_reason}"
    )


@app.command()
def scan(
    target: Path = typer.Argument(
        Path("."), help="File or directory to verify against anti-slop rules."
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit 2 when any BLOCKER or WARN occurs."),
) -> None:
    """Scan a file or repository recursively with sub-second C++20 + AST checks."""
    report = (
        scan_source(target.read_text(encoding="utf-8", errors="ignore"), file_path=str(target))
        if target.is_file()
        else scan_directory(target)
    )
    console.print(
        f"[bold]{report.verdict.value}[/] | files={report.files_scanned} lines={report.total_lines} "
        f"risk={report.risk_score}/100 blockers={report.blocker_count} warnings={report.warning_count} "
        f"({report.scan_duration_ms:.2f}ms)"
    )
    for f in report.findings[:25]:
        console.print(f"  [{f.severity.value}] {f.file_path}:{f.line} {f.rule_id} — {f.message}")
    if report.verdict == GateVerdict.BLOCK or (strict and report.verdict != GateVerdict.PASS):
        raise typer.Exit(code=2)


@app.command("claude-hook")
def claude_hook() -> None:
    """Evaluate a Claude Code JSON hook payload from stdin (exits 2 on BLOCK)."""
    code = run_claude_hook_stdio()
    if code != 0:
        raise typer.Exit(code=code)


@app.command("eval-ollama")
def eval_ollama(
    model: str = typer.Option("qwen3.5:4b", "--model"),
    base_url: str = typer.Option("http://127.0.0.1:11434", "--base-url"),
    live_only: bool = typer.Option(False, "--live-only"),
) -> None:
    """Benchmark unguarded AI slop vs slopguard-guided self-repair with local Ollama."""
    report = run_real_slop_ollama_audit(
        model=model, base_url=base_url, allow_offline_replay=not live_only
    )
    tbl = Table(title=f"Live Ollama Repair Audit ({report.model} | {report.execution_mode})")
    tbl.add_column("Task")
    tbl.add_column("Lang")
    tbl.add_column("v1 (Raw -> Blockers)")
    tbl.add_column("v2 (Guided -> Blockers)")
    tbl.add_column("Syntax Valid")
    tbl.add_column("Latency (ms)", justify="right")
    for t in report.tasks:
        tbl.add_row(
            f"{t.task_id}: {t.title}",
            t.language,
            f"{t.v1_verdict.value} ({t.v1_blockers})",
            f"{t.v2_verdict.value} ({t.v2_blockers})",
            str(t.v2_syntax_valid),
            f"{t.repair_latency_ms:.1f}",
        )
    console.print(tbl)
    console.print(
        f"[bold green]Pass Rate:[/] v1={report.v1_pass_rate_pct:.1f}% -> v2={report.v2_pass_rate_pct:.1f}% | "
        f"Blockers Eliminated={report.total_blockers_eliminated} | Avg Latency={report.avg_repair_latency_ms:.1f}ms"
    )


@app.command("mcp-stdio")
def mcp_stdio() -> None:
    """Start the zero-dependency JSON-RPC 2.0 MCP server over stdio."""
    SlopGuardMCPServer().serve_streams()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8120, "--port"),
) -> None:
    """Launch the slopguard FastAPI + React/TS Audit Console."""
    uvicorn.run(create_app(), host=host, port=port, log_level="info")

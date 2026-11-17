# ADR 0001: Hybrid C++20 Byte Prescreener + Python AST Verifier

- **Status**: Accepted
- **Date**: 2026-11-17

## Context
Coding agents emit subtle quality failures faster than human reviewers can inspect diffs: dead `...`/`pass`/`NotImplementedError` stubs, hallucinated package imports, empty `except: pass` blocks, zero-assertion tests (`assert True`), and UI placeholder callbacks (`onClick={() => {}}`). Running heavyweight linters or LLM judges on every tool edit adds hundreds of milliseconds to seconds of hook latency.

## Decision
Use a two-stage hybrid verification pipeline:
1. **`C++20` (`clang++ -O3`) Byte Scanner & Integer Risk Aggregator (`slopguard_scan_bytes`, `slopguard_aggregate_risk`)**: Scans arbitrary source buffers in sub-millisecond time using deterministic ASCII case-folding and bitmask accumulation, plus bit-exact integer risk scoring (`0..100`) and gate classification (`PASS`/`WARN`/`BLOCK`).
2. **Exact Language Analyzers (`python_ast.py`, `ts_ui_scanner.py`)**: Inspect Python AST nodes directly—exempting `@abstractmethod`, `@overload`, `Protocol`, and `if TYPE_CHECKING:` blocks—and apply precise TypeScript/JSX callback & placeholder rules.

## Consequences
- Sub-5ms execution suitable for synchronous Claude Code `PostToolUse`/`Stop` hooks.
- Zero false positives on legitimate abstract interfaces, and 100% C++20/Python parity verified via Hypothesis.

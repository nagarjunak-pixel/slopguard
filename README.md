# slopguard

[![SlopGuard CI](https://github.com/nagarjunak-pixel/slopguard/actions/workflows/ci.yml/badge.svg)](https://github.com/nagarjunak-pixel/slopguard/actions/workflows/ci.yml)
[![Release v1.0.0](https://img.shields.io/badge/release-v1.0.0-10b981)](https://github.com/nagarjunak-pixel/slopguard/releases/tag/v1.0.0)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A fast, heuristic checker for common failure patterns in AI-generated code: Python AST rules, regex-based TypeScript/JSX rules, a C++20 byte prescreener and risk aggregator (with a pure-Python fallback), a Claude Code `PostToolUse` hook, and an MCP server.**

AI coding agents can produce diffs faster than reviewers can spot recurring failure patterns: imports that do not resolve, empty `...`/`pass`/`NotImplementedError` stub bodies, `except Exception: pass`, tautological `assert True` or assertion-free tests, `eval()` sinks, and dead `onClick={() => {}}` handlers. `slopguard` flags these deterministically, typically in well under a millisecond per file, and exempts legitimate stubs (`@abstractmethod`, `@overload`, `Protocol`, `.pyi`, `if TYPE_CHECKING:`). It is a small rule-based linter (~1.75k lines of Python plus a ~170-line C++20 kernel), complementary to tests, type checkers and code review — not a replacement for them.

---

![slopguard Audit Console](docs/assets/workbench-preview.png)

## Architecture

```mermaid
flowchart LR
    Edit["Agent Code / Diff<br/>(.py · .ts · .tsx · Claude Hook stdin)"] --> Prescreen["C++20 Byte Scanner (clang++ -O3)<br/>(Bitmask flags: TODO / NotImplementedError / eval / assert True)"]
    Edit --> PyAST["Python AST Analyzer<br/>(Imports + Dead Stubs + Silent Excepts + Test Asserts)"]
    Edit --> TSUI["TypeScript / JSX UI Scanner<br/>(Empty handlers · Tautologies · XSS sinks)"]
    Prescreen --> RiskGate["C++20 Integer Risk Aggregator<br/>(0–100 score -> PASS / WARN / BLOCK)"]
    PyAST --> RiskGate
    TSUI --> RiskGate
    RiskGate -->|BLOCK exit=2| Hook["Claude Code PostToolUse Hook<br/>(Forces Self-Repair Before Final Turn)"]
    RiskGate --> UI["MCP stdio Server (.mcp.json)<br/>& Audit Console (:8120)"]
```

---

## Measured Verification & Benchmarks

Verified locally (`Python 3.13.9`, `clang++ -O3` C++20, `Ollama qwen3.5:4b`):

| Check / Benchmark | Exact Measured Result |
| :--- | :--- |
| **Static Quality Gates** | `0` Ruff format issues · `0` Ruff lint issues · `0` Mypy `--strict` errors (`21` files) |
| **Pytest + Hypothesis Suite** | **`12 passed` · `97.12%` statement coverage** (differential C++20 vs Python parity across `scan_bytes` & `aggregate_risk`) |
| **`slopguard demo` Latency** | `0.203ms` (Sloppy Python `BLOCK 100/100`) · `0.284ms` (Clean Python `PASS 0/100`) · `0.041ms` (Sloppy React TSX `BLOCK 70/100`) · `0.030ms` (Clean TSX `PASS 0/100`) |
| **Claude Code Hook Gate** | Returns `decision: "block"` (`exit=2`) on hallucinated imports, `TODO` stubs, silent `except: pass`, and `eval()` sinks |
| **Live `qwen3.5:4b` Repair Audit (`6` tasks)** | **`v1 = 0.0%` (`0/6` passing) → `v2 = 100.0%` (`6/6` passing + `v2_syntax_valid = True`)** · **`9` blockers eliminated** · **`2,157.07 ms` avg repair time** |

### Live Ollama (`qwen3.5:4b`) Guided Self-Repair Breakdown

Full artifact: [`benchmarks/real_qwen_slopguard.json`](benchmarks/real_qwen_slopguard.json)

| Task | Lang | v1 Slop (Blockers / Risk) | v2 Guarded (Blockers / Risk) | Syntax Valid | Latency |
| :--- | :--- | :---: | :---: | :---: | ---: |
| `SG-01` Hallucinated Import + JWT Stub | `python` | `BLOCK` (`2` / `95`) | **`PASS`** (`0` / `0`) | `True` | `6003.52 ms` |
| `SG-02` Silent Except Swallow + Empty Dict | `python` | `BLOCK` (`2` / `83`) | **`PASS`** (`0` / `0`) | `True` | `1437.16 ms` |
| `SG-03` Tautological Pytest (`assert True`) | `python` | `BLOCK` (`1` / `65`) | **`PASS`** (`0` / `0`) | `True` | `800.17 ms` |
| `SG-04` Dead React `onClick={() => {}}` | `tsx` | `BLOCK` (`1` / `72`) | **`PASS`** (`0` / `0`) | `True` | `1494.36 ms` |
| `SG-05` `eval()` Sink + `NotImplementedError` | `python` | `BLOCK` (`2` / `100`) | **`PASS`** (`0` / `0`) | `True` | `2015.57 ms` |
| `SG-06` TypeScript `expect(true).toBe(true)` | `typescript` | `BLOCK` (`1` / `85`) | **`PASS`** (`0` / `0`) | `True` | `1191.66 ms` |

## Scope & Limitations

- **Heuristics, not proofs.** Python checks are AST pattern rules; TypeScript/JSX checks are regex/line-based (no TS parser), so they can miss obfuscated cases and can false-positive on unusual formatting. The placeholder-phrase rule (e.g. "todo", "placeholder") is intentionally noisy in UI/text files.
- **Import resolution depends on the environment.** "Unresolved import" means the module is not in the stdlib, not a workspace module, and not found by `importlib.util.find_spec` in the interpreter running `slopguard`. Run it in the project's own environment, or expect false positives.
- **Small, self-constructed benchmark.** The live audit is 6 hand-written "sloppy" snippets repaired once by a local `qwen3.5:4b` model at temperature 0. `v2 PASS` means slopguard's own rules no longer fire and the output parses — it does **not** mean the repaired code is functionally correct, and the evaluation is circular by design (it measures whether findings are actionable).
- **Latency numbers** are single runs of `slopguard demo` on small snippets on one laptop; large files and whole-repo scans will be slower.
- **Language coverage** is Python and TypeScript/JSX only.

## Install

```bash
# From PyPI (once published)
pip install slopguard

# From source (today)
git clone https://github.com/nagarjunak-pixel/slopguard.git && cd slopguard
uv sync --all-extras        # or: pip install .
```

The C++20 prescreener source ([`src/slopguard/_csrc/slopguard_kernels.cpp`](src/slopguard/_csrc/slopguard_kernels.cpp)) ships inside the package and is compiled on first import with `clang++` or `g++` (cached in your temp dir). If no compiler is available, `slopguard` falls back to an equivalent pure-Python implementation. The React audit console (`slopguard serve`) and the recorded benchmark replay need a source checkout.

---

## Quickstart

### 1. Install, Run Demo & Scan Any Repository
```bash
uv sync --all-extras
uv run slopguard demo
uv run slopguard scan . --strict
```

### 2. Enable Claude Code `PostToolUse` Auto-Verification Hook (`.claude/settings.json`)
```json
{
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
}
```

### 3. Drop-In Claude Code / Cursor MCP Server (`.mcp.json`)
```json
{
  "mcpServers": {
    "slopguard": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/slopguard", "slopguard", "mcp-stdio"]
    }
  }
}
```

### 4. Interactive Audit Console & Live Ollama Re-Audit
```bash
cd ui && npm install && npm run build && cd ..
uv run slopguard eval-ollama --live-only
uv run slopguard serve --host 127.0.0.1 --port 8120
```

See [ADR 0001](docs/adr/0001-hybrid-cpp20-prescreener-and-ast-verifier.md) for the integer risk kernel and AST exemption rules.

---

## Author, LinkedIn & Enterprise AI Architecture Hub
Built by **[Nagarjuna Reddy Kamireddy](https://nagarjunak-pixel.github.io/)** (*Nagarjuna Kamireddy / Nagarjuna K*) — Lead AI Architect | Production Agentic AI, Hybrid RAG & LLM Evals (750K+ Workflows/Yr) | Ex-John Deere, GSK, Deloitte | AWS SA Pro & NVIDIA Agentic AI Certified.

- **Official LinkedIn & Daily Newsletter:** [linkedin.com/in/nagarjuna-kamireddy](https://www.linkedin.com/in/nagarjuna-kamireddy/) · [Autonomous SAP & Enterprise AI Newsletter](https://www.linkedin.com/newsletters/autonomous-sap-enterprise-ai-7528104436112441348/)
- **Canonical Portfolio & All 50 GitHub Projects:** [nagarjunak-pixel.github.io](https://nagarjunak-pixel.github.io/) · [Complete GitHub Atlas](https://nagarjunak-pixel.github.io/github-projects-atlas.html) · [`llms-full.txt`](https://nagarjunak-pixel.github.io/llms-full.txt)

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- Packaging: the C++20 kernel source moved from `csrc/` to `src/slopguard/_csrc/` so it ships
  inside the wheel and sdist; the loader now resolves it relative to the installed package, so the
  native prescreener compiles after `pip install` (previously an installed wheel silently used the
  Python fallback).
- `pyproject.toml`: added keywords, classifiers, project URLs, `py.typed` marker and an explicit
  sdist include list in preparation for a PyPI release.
- Docs: plainer project description, a "Scope & Limitations" section and an "Install" section.

## [1.0.0] - 2026-11-17

### Added
- Python AST analyzer: unresolved imports (checked against stdlib, workspace modules and
  `importlib.util.find_spec`), dead stub bodies (`pass` / `...` / `raise NotImplementedError` / empty returns),
  silent `except: pass`, `eval()`/`exec()` sinks, tautological or missing test assertions; with
  exemptions for `@abstractmethod`, `@overload`, `Protocol`, `.pyi` and `if TYPE_CHECKING:`.
- Regex/line-based TypeScript/JSX scanner for empty event handlers, empty or tautological
  `expect(...)` tests, `dangerouslySetInnerHTML` / `eval(` sinks and placeholder copy.
- C++20 byte prescreener (bitmask flags for `TODO`, `NotImplementedError`, `eval`, `assert True`, …)
  and integer 0–100 risk aggregator (`clang++ -O3`, loaded via `ctypes`)
  with a pure-Python reference implementation and differential Hypothesis tests.
- Claude Code `PostToolUse` hook (`slopguard claude-hook`, exit code 2 on BLOCK), MCP stdio server,
  `scan` / `demo` / `eval-ollama` / `serve` CLI commands, FastAPI API and React audit console.
- Six-task guided self-repair audit against a local `qwen3.5:4b` model via Ollama
  (`benchmarks/real_qwen_slopguard.json`).

[Unreleased]: https://github.com/nagarjunak-pixel/slopguard/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/nagarjunak-pixel/slopguard/releases/tag/v1.0.0

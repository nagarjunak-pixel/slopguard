"""Zero-Dependency JSON-RPC 2.0 Model Context Protocol (`MCP`) Server for Claude Code / Cursor.

Exposes 4 agent-ready tools over stdio (`slopguard mcp-stdio`) and in-process RPC:
- `slopguard_scan_code`: Scan a Python/TypeScript/JSX source snippet with C++20 + AST verification
- `slopguard_scan_repo`: Recursively audit a local workspace directory against slop rules
- `slopguard_check_claude_hook`: Evaluate a Claude Code Write/Edit hook JSON payload
- `slopguard_explain_rules`: Return full SG000..SG008 rule catalog and remediation guidance
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any

from slopguard.analyzers.gate_engine import scan_directory, scan_source
from slopguard.hooks.claude_hook import evaluate_claude_hook_payload

RULE_CATALOG: list[dict[str, str]] = [
    {
        "id": "SG001_HALLUCINATED_IMPORT",
        "severity": "BLOCKER",
        "summary": "Non-existent package import outside stdlib, declared deps, and installed env.",
    },
    {
        "id": "SG002_DEAD_STUB_BODY",
        "severity": "BLOCKER",
        "summary": "Unimplemented pass / ... / NotImplementedError / empty return stub (exempts @abstractmethod / Protocol).",
    },
    {
        "id": "SG003_SILENT_SWALLOW_EXCEPT",
        "severity": "BLOCKER",
        "summary": "Silent exception handler swallowing failures with pass or empty return.",
    },
    {
        "id": "SG004_FAKE_TEST_ASSERTION",
        "severity": "BLOCKER",
        "summary": "Python test with assert True tautology or zero assertions / pytest.raises checks.",
    },
    {
        "id": "SG005_UNSAFE_DYNAMIC_EXEC",
        "severity": "BLOCKER/WARN",
        "summary": "Dangerous eval/exec or shell=True subprocess call.",
    },
    {
        "id": "SG006_UI_PLACEHOLDER_SLOP",
        "severity": "BLOCKER/WARN",
        "summary": "Empty UI handler onClick={() => {}} or unresolved TODO / Lorem ipsum / Coming soon copy.",
    },
    {
        "id": "SG007_TAUTOLOGY_JS_ASSERT",
        "severity": "BLOCKER",
        "summary": "Empty JS/TS test block or expect(true).toBe(true) tautology.",
    },
    {
        "id": "SG008_XSS_UNSAFE_SINK",
        "severity": "BLOCKER",
        "summary": "dangerouslySetInnerHTML or dynamic eval sink in frontend UI.",
    },
]


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "slopguard_scan_code",
            "description": "Scan Python, TypeScript, JSX, or TSX code for hallucinated imports, dead stubs, silent exception swallowing, fake test assertions, and unsafe UI placeholders.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "file_path": {"type": "string", "default": "module.py"},
                    "known_modules": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["source"],
            },
        },
        {
            "name": "slopguard_scan_repo",
            "description": "Scan a local directory recursively for anti-slop violations and compute integer C++20 risk score + PASS/WARN/BLOCK verdict.",
            "inputSchema": {
                "type": "object",
                "properties": {"root_dir": {"type": "string"}},
                "required": ["root_dir"],
            },
        },
        {
            "name": "slopguard_check_claude_hook",
            "description": "Evaluate a Claude Code PreToolUse/PostToolUse Write or Edit JSON payload and return allow/block decision.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool_input": {"type": "object"},
                    "cwd": {"type": "string"},
                },
                "required": ["tool_input"],
            },
        },
        {
            "name": "slopguard_explain_rules",
            "description": "List all slopguard anti-slop rule IDs, severities, and remediation standards.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


class SlopGuardMCPServer:
    """In-process and stdio JSON-RPC 2.0 MCP server for slopguard."""

    def handle_request(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = str(msg.get("method", ""))
        req_id = msg.get("id")

        if method == "notifications/initialized" or req_id is None:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "slopguard-mcp", "version": "1.0.0"},
                },
            }

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_definitions()}}

        if method == "tools/call":
            params = msg.get("params", {})
            name = str(params.get("name", ""))
            args = params.get("arguments", {}) or {}
            try:
                payload = self._dispatch_tool(name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error in {name}: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "slopguard_scan_code":
            known = {str(m) for m in (args.get("known_modules") or [])}
            report = scan_source(
                source=str(args["source"]),
                file_path=str(args.get("file_path", "module.py")),
                known_modules=known or None,
            )
            return report.model_dump()

        if name == "slopguard_scan_repo":
            report = scan_directory(Path(str(args["root_dir"])))
            return report.model_dump()

        if name == "slopguard_check_claude_hook":
            code, resp = evaluate_claude_hook_payload(args)
            return {"exit_code": code, **resp}

        if name == "slopguard_explain_rules":
            return {"rules": RULE_CATALOG}

        raise ValueError(f"Unknown MCP tool: {name}")

    def serve_streams(self, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                resp = self.handle_request(msg)
                if resp is not None:
                    stdout.write(json.dumps(resp) + "\n")
                    stdout.flush()
            except Exception as exc:
                stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32700, "message": str(exc)},
                        }
                    )
                    + "\n"
                )
                stdout.flush()

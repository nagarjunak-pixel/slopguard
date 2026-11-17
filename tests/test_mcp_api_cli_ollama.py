"""Tests for MCP stdio server, FastAPI endpoints, Typer CLI & Ollama audit."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from slopguard.api.app import create_app
from slopguard.audit.ollama_slop import extract_code_block, run_real_slop_ollama_audit
from slopguard.cli import app as cli_app
from slopguard.demo import CLEAN_PYTHON_SAMPLE, SLOPPY_PYTHON_SAMPLE
from slopguard.mcp.server import SlopGuardMCPServer
from slopguard.types import GateVerdict, RealSlopAuditReport


def test_mcp_server_rpc_and_stdio(tmp_path: Path) -> None:
    srv = SlopGuardMCPServer()
    assert srv.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    init_resp = srv.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init_resp is not None and init_resp["result"]["serverInfo"]["name"] == "slopguard-mcp"

    list_resp = srv.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert list_resp is not None
    assert len(list_resp["result"]["tools"]) == 4

    scan_resp = srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "slopguard_scan_code",
                "arguments": {"source": SLOPPY_PYTHON_SAMPLE, "file_path": "payouts.py"},
            },
        }
    )
    assert scan_resp is not None and scan_resp["result"]["isError"] is False

    (tmp_path / "clean.py").write_text(CLEAN_PYTHON_SAMPLE, encoding="utf-8")
    repo_resp = srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "slopguard_scan_repo", "arguments": {"root_dir": str(tmp_path)}},
        }
    )
    assert repo_resp is not None and repo_resp["result"]["isError"] is False

    hook_resp = srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "slopguard_check_claude_hook",
                "arguments": {"tool_input": {"file_path": "a.py", "content": SLOPPY_PYTHON_SAMPLE}},
            },
        }
    )
    assert hook_resp is not None and hook_resp["result"]["isError"] is False

    rules_resp = srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "slopguard_explain_rules", "arguments": {}},
        }
    )
    assert rules_resp is not None and rules_resp["result"]["isError"] is False

    err_tool = srv.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "bad_tool", "arguments": {}},
        }
    )
    assert err_tool is not None and err_tool["result"]["isError"] is True

    err_method = srv.handle_request({"jsonrpc": "2.0", "id": 8, "method": "bad/method"})
    assert err_method is not None and err_method["error"]["code"] == -32601

    stdin = io.StringIO('\n{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n{invalid json\n')
    stdout = io.StringIO()
    srv.serve_streams(stdin=stdin, stdout=stdout)
    out_lines = stdout.getvalue().strip().splitlines()
    assert len(out_lines) == 2 and json.loads(out_lines[1])["error"]["code"] == -32700


def test_fastapi_endpoints_and_cli(tmp_path: Path) -> None:
    client = TestClient(create_app())
    assert client.get("/api/v1/health").json()["service"] == "slopguard"
    assert client.get("/api/v1/demo").status_code == 200
    assert (
        client.post(
            "/api/v1/scan", json={"source": CLEAN_PYTHON_SAMPLE, "file_path": "payouts.py"}
        ).json()["verdict"]
        == "PASS"
    )
    (tmp_path / "mod.py").write_text(CLEAN_PYTHON_SAMPLE, encoding="utf-8")
    assert client.post("/api/v1/scan-repo", json={"root_dir": str(tmp_path)}).status_code == 200
    assert client.get("/").status_code == 200

    runner = CliRunner()
    assert runner.invoke(cli_app, ["demo"]).exit_code == 0
    assert runner.invoke(cli_app, ["scan", str(tmp_path), "--strict"]).exit_code == 0

    bad_file = tmp_path / "slop.py"
    bad_file.write_text(SLOPPY_PYTHON_SAMPLE, encoding="utf-8")
    assert runner.invoke(cli_app, ["scan", str(bad_file)]).exit_code == 2
    assert (
        runner.invoke(
            cli_app,
            ["claude-hook"],
            input=json.dumps(
                {"tool_input": {"file_path": "clean.py", "content": CLEAN_PYTHON_SAMPLE}}
            ),
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            cli_app,
            ["claude-hook"],
            input=json.dumps(
                {"tool_input": {"file_path": "bad.py", "content": SLOPPY_PYTHON_SAMPLE}}
            ),
        ).exit_code
        == 2
    )


def test_ollama_slop_audit_isolated(tmp_path: Path) -> None:
    assert "x = 1" in extract_code_block("```python\nx = 1\n```")
    assert "x = 2" in extract_code_block("x = 2")

    out_art = tmp_path / "real_qwen_slopguard.json"

    class _FakeResp:
        def __init__(self, code: str) -> None:
            self._code = code

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"message": {"content": self._code}}

    def _fake_post(url: str, json: dict[str, object], timeout: float) -> _FakeResp:
        msgs = json["messages"]
        assert isinstance(msgs, list)
        user_prompt = str(msgs[1]["content"])
        if ".tsx" in user_prompt or ".ts" in user_prompt:
            if "test(" in user_prompt:
                return _FakeResp(
                    "```tsx\nconst applyDiscount = (p: number, pct: number) => p * (100 - pct) / 100;\n"
                    'test("applies coupon", () => { expect(applyDiscount(200, 15)).toBe(170); });\n```'
                )
            return _FakeResp(
                "```tsx\nimport React, { useState } from 'react';\n"
                "export function SyncButton() {\n  const [c, setC] = useState(0);\n"
                "  return <button onClick={() => setC(c + 1)}>Synced runs: {c}</button>;\n}\n```"
            )
        if "def test_" in user_prompt:
            return _FakeResp(
                "```python\ndef test_checkout_total() -> None:\n    assert 3 * 250 + 75 == 825\n```"
            )
        return _FakeResp(
            "```python\nimport hmac\nimport hashlib\n\n"
            "def compute_verified(secret: bytes, payload: bytes) -> str:\n"
            "    return hmac.new(secret, payload, hashlib.sha256).hexdigest()\n```"
        )

    with (
        patch("slopguard.api.app.default_slop_audit_path", return_value=out_art),
        patch("slopguard.audit.ollama_slop.default_slop_audit_path", return_value=out_art),
        patch("slopguard.audit.ollama_slop.httpx.post", side_effect=_fake_post),
    ):
        rep = run_real_slop_ollama_audit(output_path=out_art)
        assert rep.v1_pass_rate_pct == 0.0
        assert rep.v2_pass_rate_pct == 100.0
        assert all(t.v2_verdict == GateVerdict.PASS for t in rep.tasks)

        client = TestClient(create_app())
        assert client.get("/api/v1/audit/ollama?refresh=true").status_code == 200
        assert client.get("/api/v1/audit/ollama").status_code == 200

        runner = CliRunner()
        assert runner.invoke(cli_app, ["eval-ollama"]).exit_code == 0

    with patch("slopguard.audit.ollama_slop.httpx.post", side_effect=RuntimeError("offline")):
        replayed = run_real_slop_ollama_audit(allow_offline_replay=True, output_path=out_art)
        assert isinstance(replayed, RealSlopAuditReport)
        assert replayed.execution_mode == "recorded-artifact-replay"

        with pytest.raises(RuntimeError):
            run_real_slop_ollama_audit(allow_offline_replay=False, output_path=out_art)

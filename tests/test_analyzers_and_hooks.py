"""Unit tests for Python AST rules, exemptions, TS/JSX UI scanner, repo scanner & Claude hook."""

from __future__ import annotations

import io
import json
from pathlib import Path

from slopguard.analyzers.gate_engine import scan_directory, scan_source
from slopguard.analyzers.python_ast import inspect_python_source
from slopguard.demo import CLEAN_PYTHON_SAMPLE, build_demo_showcase
from slopguard.hooks.claude_hook import evaluate_claude_hook_payload, run_claude_hook_stdio
from slopguard.types import GateVerdict


def test_python_ast_exemptions_and_clean_code() -> None:
    clean = scan_source(CLEAN_PYTHON_SAMPLE, file_path="src/payouts.py")
    assert clean.verdict == GateVerdict.PASS
    assert clean.blocker_count == 0

    abstract_and_protocol = """
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, overload

if TYPE_CHECKING:
    import nonexistent_type_only_pkg

class StorageProto(Protocol):
    def get(self, key: str) -> str:
        ...

class BaseStore(ABC):
    @abstractmethod
    def put(self, key: str, value: str) -> None:
        pass

    @overload
    def coerce(self, val: int) -> int: ...

    @overload
    def coerce(self, val: str) -> str: ...

    def coerce(self, val: int | str) -> int | str:
        return val
"""
    rep = scan_source(abstract_and_protocol, file_path="src/interfaces.py")
    assert rep.verdict == GateVerdict.PASS
    assert rep.blocker_count == 0
    assert inspect_python_source(abstract_and_protocol, file_path="types.pyi") == []


def test_python_ast_catches_all_slop_classes() -> None:
    slop = """
import fake_ai_helper
from bogus_cloud_sdk import deploy_all
import subprocess

def empty_stub() -> None:
    pass

def test_tautology() -> None:
    assert True
    assert 1 == 1
    assert not False

def test_no_assertions() -> None:
    x = 2 + 2

def dangerous(cmd: str) -> None:
    exec(cmd)
    subprocess.run(cmd, shell=True)
"""
    rep = scan_source(slop, file_path="tests/test_bad.py")
    assert rep.verdict == GateVerdict.BLOCK
    rules = set(rep.rule_counts)
    assert "SG001_HALLUCINATED_IMPORT" in rules
    assert "SG002_DEAD_STUB_BODY" in rules
    assert "SG004_FAKE_TEST_ASSERTION" in rules
    assert "SG005_UNSAFE_DYNAMIC_EXEC" in rules

    syn = scan_source("def oops(:\n", file_path="broken.py")
    assert syn.verdict == GateVerdict.BLOCK
    assert "SG000_SYNTAX_ERROR" in syn.rule_counts


def test_tsx_scanner_and_repository_scan(tmp_path: Path) -> None:
    demo = build_demo_showcase()
    assert demo.sloppy_py_report.verdict == GateVerdict.BLOCK
    assert demo.sloppy_tsx_report.verdict == GateVerdict.BLOCK
    assert demo.clean_tsx_report.verdict == GateVerdict.PASS

    unsafe_tsx = """
export function UnsafeWidget({ rawHtml }: { rawHtml: string }) {
  return <div dangerouslySetInnerHTML={{ __html: rawHtml }} />;
}
test("empty", () => {});
expect(true).toBe(true);
"""
    rep = scan_source(unsafe_tsx, file_path="ui/UnsafeWidget.tsx")
    assert rep.verdict == GateVerdict.BLOCK
    assert "SG007_TAUTOLOGY_JS_ASSERT" in rep.rule_counts
    assert "SG008_XSS_UNSAFE_SINK" in rep.rule_counts

    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["my-custom-dep>=1.0"]\n')
    (tmp_path / "src" / "myapp").mkdir(parents=True)
    (tmp_path / "src" / "myapp" / "__init__.py").write_text("")
    (tmp_path / "src" / "myapp" / "app.py").write_text(
        "import my_custom_dep\nfrom myapp import core\n\ndef add(a: int, b: int) -> int:\n    return a + b\n"
    )
    (tmp_path / "src" / "myapp" / "core.py").write_text("VAL = 42\n")

    repo_rep = scan_directory(tmp_path)
    assert repo_rep.files_scanned == 3
    assert repo_rep.verdict == GateVerdict.PASS


def test_claude_hook_evaluation_and_stdio(tmp_path: Path) -> None:
    demo = build_demo_showcase()
    assert demo.claude_hook_exit_code == 2
    assert demo.claude_hook_decision == "block"

    code_allow, resp_allow = evaluate_claude_hook_payload(
        {"tool_input": {"file_path": "ok.py", "content": ""}}
    )
    assert code_allow == 0 and resp_allow["decision"] == "allow"

    code_clean, resp_clean = evaluate_claude_hook_payload(
        {
            "tool_input": {"file_path": "clean.py", "content": CLEAN_PYTHON_SAMPLE},
            "cwd": str(tmp_path),
        }
    )
    assert code_clean == 0 and resp_clean["decision"] == "allow"

    out = io.StringIO()
    exit_empty = run_claude_hook_stdio(stdin=io.StringIO(""), stdout=out)
    assert exit_empty == 0

    out_block = io.StringIO()
    payload = json.dumps(
        {
            "tool_input": {
                "file_path": "bad.py",
                "content": "def bad():\n    raise NotImplementedError()\n",
            }
        }
    )
    exit_block = run_claude_hook_stdio(stdin=io.StringIO(payload), stdout=out_block)
    assert exit_block == 2
    assert json.loads(out_block.getvalue())["decision"] == "block"


def test_python_ast_extra_attribute_branches() -> None:
    src = """
import abc
import builtins
import typing

if typing.TYPE_CHECKING:
    import type_only_imaginary_pkg

class ProtoAttr(typing.Protocol):
    def ping(self) -> str: ...

class AbsAttr(abc.ABC):
    @abc.abstractmethod
    def go(self) -> None:
        return None

def ret_bare() -> None:
    return

def ret_none() -> None:
    return None

def raise_attr() -> None:
    raise builtins.NotImplementedError()

def cond_branch(flag: bool) -> None:
    if flag:
        import another_fake_pkg
    else:
        return

def test_pytest_raises_passes(mock_obj: object) -> None:
    import pytest
    with pytest.raises(ValueError):
        raise ValueError("ok")
"""
    rep = scan_source(src, file_path="src/extra_branches.py")
    assert "SG001_HALLUCINATED_IMPORT" in rep.rule_counts
    assert "SG002_DEAD_STUB_BODY" in rep.rule_counts
    assert "SG004_FAKE_TEST_ASSERTION" not in rep.rule_counts

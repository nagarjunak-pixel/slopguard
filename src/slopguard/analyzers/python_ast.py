"""AST-aware Python anti-slop analyzer checking hallucinated imports, dead stubs, silent excepts & fake tests."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from slopguard.types import Severity, SlopFinding

_EXEMPT_DECORATORS = {"abstractmethod", "overload"}
_SILENT_RETURN_LITERALS = (type(None),)


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
    return names


def _is_protocol_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _is_type_checking_guard(node: ast.If) -> bool:
    if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
        return True
    if isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING":
        return True
    return False


def _module_exists(pkg: str, known_modules: set[str]) -> bool:
    if not pkg or pkg in sys.stdlib_module_names or pkg in known_modules:
        return True
    try:
        return importlib.util.find_spec(pkg) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_dead_stub_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        exc = stmt.exc
        if isinstance(exc, ast.Call):
            exc = exc.func
        if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
            return True
        if isinstance(exc, ast.Attribute) and exc.attr == "NotImplementedError":
            return True
    if isinstance(stmt, ast.Return):
        val = stmt.value
        if val is None:
            return True
        if isinstance(val, ast.Constant) and isinstance(val.value, _SILENT_RETURN_LITERALS):
            return True
        if isinstance(val, (ast.Dict, ast.List)) and not (
            isinstance(val, ast.Dict) and val.keys or isinstance(val, ast.List) and val.elts
        ):
            return True
    return False


def _is_tautological_assert(test: ast.expr) -> bool:
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Constant)
        and test.operand.value is False
    ):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        op = test.ops[0]
        left, right = test.left, test.comparators[0]
        if (
            isinstance(op, ast.Eq)
            and isinstance(left, ast.Constant)
            and isinstance(right, ast.Constant)
            and left.value == right.value
        ):
            return True
    return False


def _has_real_test_assertion(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert) and not _is_tautological_assert(node.test):
            return True
        if isinstance(node, ast.Call):
            fn_expr = node.func
            if isinstance(fn_expr, ast.Attribute) and (
                fn_expr.attr == "raises" or fn_expr.attr.startswith("assert_")
            ):
                return True
    return False


def _collect_findings(
    stmts: list[ast.stmt],
    lines: list[str],
    file_path: str,
    known_modules: set[str],
    in_protocol: bool,
    findings: list[SlopFinding],
) -> None:
    def _snippet(line_no: int) -> str:
        return lines[line_no - 1].strip() if 1 <= line_no <= len(lines) else ""

    for stmt in stmts:
        if isinstance(stmt, ast.If):
            if _is_type_checking_guard(stmt):
                continue
            _collect_findings(stmt.body, lines, file_path, known_modules, in_protocol, findings)
            _collect_findings(stmt.orelse, lines, file_path, known_modules, in_protocol, findings)
            continue

        if isinstance(stmt, ast.ClassDef):
            is_proto = in_protocol or _is_protocol_class(stmt)
            _collect_findings(stmt.body, lines, file_path, known_modules, is_proto, findings)
            continue

        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                root = alias.name.split(".", 1)[0]
                if not _module_exists(root, known_modules):
                    findings.append(
                        SlopFinding(
                            rule_id="SG001_HALLUCINATED_IMPORT",
                            severity=Severity.BLOCKER,
                            weight=35,
                            file_path=file_path,
                            line=stmt.lineno,
                            message=f"Import '{alias.name}' does not resolve to stdlib, workspace, or installed package.",
                            remediation="Replace hallucinated package with a verified dependency or real standard-library module.",
                            snippet=_snippet(stmt.lineno),
                        )
                    )
            continue

        if isinstance(stmt, ast.ImportFrom):
            if stmt.level == 0 and stmt.module:
                root = stmt.module.split(".", 1)[0]
                if not _module_exists(root, known_modules):
                    findings.append(
                        SlopFinding(
                            rule_id="SG001_HALLUCINATED_IMPORT",
                            severity=Severity.BLOCKER,
                            weight=35,
                            file_path=file_path,
                            line=stmt.lineno,
                            message=f"From-import '{stmt.module}' does not resolve to stdlib, workspace, or installed package.",
                            remediation="Verify package name against pyproject.toml / installed environment before importing.",
                            snippet=_snippet(stmt.lineno),
                        )
                    )
            continue

        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decs = _decorator_names(stmt)
            exec_body = _strip_docstring(stmt.body)
            is_test_fn = stmt.name.startswith("test_")
            is_dunder = stmt.name.startswith("__") and stmt.name.endswith("__")

            if (
                not in_protocol
                and not (decs & _EXEMPT_DECORATORS)
                and not is_dunder
                and exec_body
                and all(_is_dead_stub_stmt(inner) for inner in exec_body)
            ):
                findings.append(
                    SlopFinding(
                        rule_id="SG002_DEAD_STUB_BODY",
                        severity=Severity.BLOCKER,
                        weight=30,
                        file_path=file_path,
                        line=stmt.lineno,
                        message=f"Function '{stmt.name}' contains only a stub body (pass / ... / NotImplementedError / empty return).",
                        remediation="Implement real business logic or mark legitimate abstract interfaces with @abstractmethod / Protocol.",
                        snippet=_snippet(stmt.lineno),
                    )
                )

            if is_test_fn:
                tautologies = [
                    n
                    for n in ast.walk(stmt)
                    if isinstance(n, ast.Assert) and _is_tautological_assert(n.test)
                ]
                for taut in tautologies:
                    findings.append(
                        SlopFinding(
                            rule_id="SG004_FAKE_TEST_ASSERTION",
                            severity=Severity.BLOCKER,
                            weight=35,
                            file_path=file_path,
                            line=taut.lineno,
                            message=f"Test '{stmt.name}' uses a tautological assertion (e.g. assert True / 1 == 1).",
                            remediation="Assert concrete computed outputs or expected exception invariants.",
                            snippet=_snippet(taut.lineno),
                        )
                    )
                if not tautologies and not _has_real_test_assertion(stmt):
                    findings.append(
                        SlopFinding(
                            rule_id="SG004_FAKE_TEST_ASSERTION",
                            severity=Severity.BLOCKER,
                            weight=35,
                            file_path=file_path,
                            line=stmt.lineno,
                            message=f"Test '{stmt.name}' executes without any real assert or pytest.raises check.",
                            remediation="Add meaningful behavioral assertions verifying state transitions and edge cases.",
                            snippet=_snippet(stmt.lineno),
                        )
                    )

            for inner in ast.walk(stmt):
                if isinstance(inner, ast.ExceptHandler):
                    h_body = _strip_docstring(inner.body)
                    if h_body and all(
                        isinstance(b, (ast.Pass, ast.Continue)) or _is_dead_stub_stmt(b)
                        for b in h_body
                    ):
                        findings.append(
                            SlopFinding(
                                rule_id="SG003_SILENT_SWALLOW_EXCEPT",
                                severity=Severity.BLOCKER,
                                weight=28,
                                file_path=file_path,
                                line=inner.lineno,
                                message="Exception handler silently swallows failure via pass / empty return.",
                                remediation="Handle error explicitly, log structured context, or re-raise typed exception.",
                                snippet=_snippet(inner.lineno),
                            )
                        )
                elif isinstance(inner, ast.Call):
                    if isinstance(inner.func, ast.Name) and inner.func.id in {"eval", "exec"}:
                        findings.append(
                            SlopFinding(
                                rule_id="SG005_UNSAFE_DYNAMIC_EXEC",
                                severity=Severity.BLOCKER,
                                weight=32,
                                file_path=file_path,
                                line=inner.lineno,
                                message=f"Unsafe dynamic code execution '{inner.func.id}(...)' detected.",
                                remediation="Replace eval/exec with ast.literal_eval, explicit dispatch, or typed parser.",
                                snippet=_snippet(inner.lineno),
                            )
                        )
                    elif any(
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                        for kw in inner.keywords
                    ):
                        findings.append(
                            SlopFinding(
                                rule_id="SG005_UNSAFE_DYNAMIC_EXEC",
                                severity=Severity.WARN,
                                weight=25,
                                file_path=file_path,
                                line=inner.lineno,
                                message="Subprocess invocation with shell=True risks command injection.",
                                remediation="Pass argument list argv=[...] with shell=False.",
                                snippet=_snippet(inner.lineno),
                            )
                        )

            _collect_findings(stmt.body, lines, file_path, known_modules, False, findings)


def inspect_python_source(
    source: str,
    file_path: str = "<input>.py",
    known_modules: set[str] | None = None,
) -> list[SlopFinding]:
    """Run AST anti-slop verification across Python source text."""
    if not source.strip() or Path(file_path).suffix == ".pyi":
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            SlopFinding(
                rule_id="SG000_SYNTAX_ERROR",
                severity=Severity.BLOCKER,
                weight=45,
                file_path=file_path,
                line=exc.lineno or 1,
                message=f"Python SyntaxError: {exc.msg}",
                remediation="Fix syntax error so module compiles cleanly.",
            )
        ]

    lines = source.splitlines()
    findings: list[SlopFinding] = []
    _collect_findings(tree.body, lines, file_path, known_modules or set(), False, findings)
    return findings

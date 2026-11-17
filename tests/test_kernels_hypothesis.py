"""Differential Hypothesis fuzzing: C++20 byte scanner & risk aggregator vs Python reference."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from slopguard.kernels.native_scan import (
    active_backend_name,
    aggregate_risk,
    python_aggregate_risk,
    python_scan_bytes,
    scan_bytes,
)


def test_native_kernel_compiled_on_host() -> None:
    assert "c++20-native" in active_backend_name()


def test_empty_edge_cases() -> None:
    assert scan_bytes(b"") == ([], 0)
    assert python_scan_bytes(b"") == ([], 0)
    assert aggregate_risk([], [], 10)[1:] == (0, 0)
    assert python_aggregate_risk([], [], 10)[1:] == (0, 0)


_TEXT_ATOMS = st.sampled_from(
    [
        "def ok(): return 1\n",
        "# TODO: finish\r\n",
        "raise NotImplementedError()\n",
        "// stub implementation\n",
        "assert True\n",
        "expect(true).toBe(true)\n",
        "eval(x)\n",
        "subprocess.run('ls', shell=True)\n",
        "<div dangerouslySetInnerHTML={{__html: s}} />\n",
        "coming soon placeholder",
    ]
)


@settings(max_examples=80, deadline=None)
@given(chunks=st.lists(_TEXT_ATOMS, min_size=1, max_size=20), trailing=st.booleans())
def test_scan_bytes_cpp_python_parity(chunks: list[str], trailing: bool) -> None:
    raw = "".join(chunks)
    if trailing and not raw.endswith("\n"):
        raw += "tail"
    data = raw.encode("utf-8")
    assert scan_bytes(data) == python_scan_bytes(data)


@settings(max_examples=80, deadline=None)
@given(
    n=st.integers(min_value=1, max_value=30),
    data=st.data(),
)
def test_aggregate_risk_cpp_python_parity(n: int, data: st.DataObject) -> None:
    weights = data.draw(st.lists(st.integers(min_value=0, max_value=50), min_size=n, max_size=n))
    blockers = data.draw(st.lists(st.integers(min_value=0, max_value=1), min_size=n, max_size=n))
    total_lines = data.draw(st.integers(min_value=1, max_value=500))

    cpp_res = aggregate_risk(weights, blockers, total_lines)
    py_res = python_aggregate_risk(weights, blockers, total_lines)
    assert cpp_res == py_res
    assert 0 <= cpp_res[2] <= 100

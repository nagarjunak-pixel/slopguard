"""Native C++20 bridge (`clang++ -O3`) for Sub-Millisecond Byte Scanning & Risk Aggregation."""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from slopguard.types import GateVerdict


def _compile_native_lib() -> tuple[ctypes.CDLL | None, str]:
    src_path = Path(__file__).resolve().parents[3] / "csrc" / "slopguard_kernels.cpp"
    clang = shutil.which("clang++") or shutil.which("g++")
    if not src_path.exists() or clang is None:
        return None, "python-fallback"

    digest = hashlib.sha256(src_path.read_bytes()).hexdigest()[:16]
    out_dir = Path(tempfile.gettempdir()) / "slopguard_native_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".dylib" if Path("/System/Library").exists() else ".so"
    lib_path = out_dir / f"libslopguard_kernels_{digest}{ext}"

    if not lib_path.exists():
        cmd = [clang, "-O3", "-std=c++20", "-shared", "-fPIC", str(src_path), "-o", str(lib_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return None, "python-fallback"

    lib = ctypes.CDLL(str(lib_path))
    lib.slopguard_scan_bytes.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
    ]
    lib.slopguard_scan_bytes.restype = ctypes.c_int32

    lib.slopguard_aggregate_risk.argtypes = [
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.POINTER(ctypes.c_int32),
        ctypes.POINTER(ctypes.c_int32),
    ]
    lib.slopguard_aggregate_risk.restype = ctypes.c_int32
    return lib, "c++20-native (clang++ -O3)"


_NATIVE_LIB, _BACKEND_NAME = _compile_native_lib()

_VERDICT_MAP: dict[int, GateVerdict] = {
    0: GateVerdict.PASS,
    1: GateVerdict.WARN,
    2: GateVerdict.BLOCK,
}


def active_backend_name() -> str:
    return _BACKEND_NAME


def _ascii_lower_bytes(data: bytes) -> str:
    return "".join(chr(b + 32) if 65 <= b <= 90 else chr(b) for b in data)


def python_scan_bytes(data: bytes, max_out: int = 4096) -> tuple[list[tuple[int, int]], int]:
    if not data:
        return [], 0

    matches: list[tuple[int, int]] = []
    line_num = 0
    idx = 0
    n = len(data)
    while idx < n:
        line_num += 1
        nl = data.find(b"\n", idx)
        if nl == -1:
            nl = n
        end = nl - 1 if (nl > idx and data[nl - 1] == 13) else nl
        line_str = _ascii_lower_bytes(data[idx:end])

        mask = 0
        if any(
            k in line_str for k in ("todo", "fixme", "placeholder", "coming soon", "lorem ipsum")
        ):
            mask |= 1
        if "notimplementederror" in line_str:
            mask |= 2
        if any(
            k in line_str
            for k in (
                "stub implementation",
                "for brevity",
                "dummy return",
                "mock response",
                "in production, replace",
                "simulated only",
            )
        ):
            mask |= 4
        if any(
            k in line_str
            for k in (
                "assert true",
                "expect(true).tobe(true)",
                "expect(true).toequal(true)",
                "expect(1).tobe(1)",
            )
        ):
            mask |= 8
        if any(k in line_str for k in ("dangerouslysetinnerhtml", "eval(", "shell=true")):
            mask |= 16

        if mask != 0 and len(matches) < max_out:
            matches.append((line_num, mask))
        idx = nl + 1

    return matches, line_num


def scan_bytes(
    data: bytes, max_out: int = 4096, *, force_python: bool = False
) -> tuple[list[tuple[int, int]], int]:
    if _NATIVE_LIB is None or force_python:
        return python_scan_bytes(data, max_out=max_out)

    n = len(data)
    if n <= 0:
        return [], 0

    cap = max(1, min(max_out, n + 1))
    buf = (ctypes.c_uint8 * n).from_buffer_copy(data)
    out_lines = (ctypes.c_int32 * cap)()
    out_masks = (ctypes.c_int32 * cap)()
    out_total = ctypes.c_int32(0)

    cnt = int(
        _NATIVE_LIB.slopguard_scan_bytes(
            buf,
            n,
            out_lines,
            out_masks,
            cap,
            ctypes.byref(out_total),
        )
    )
    return [(int(out_lines[i]), int(out_masks[i])) for i in range(cnt)], int(out_total.value)


def python_aggregate_risk(
    severity_weights: list[int], is_blocker: list[int], total_lines: int
) -> tuple[GateVerdict, int, int]:
    n = len(severity_weights)
    if n <= 0:
        return GateVerdict.PASS, 0, 0

    weight_sum = sum(w for w in severity_weights if w > 0)
    blockers = sum(1 for b in is_blocker if b != 0)
    safe_lines = max(1, total_lines)
    density_bonus = min(30, (n * 100) // safe_lines)
    risk = min(100, weight_sum + density_bonus)
    if blockers > 0 or risk >= 60:
        verdict = GateVerdict.BLOCK
    elif risk >= 25:
        verdict = GateVerdict.WARN
    else:
        verdict = GateVerdict.PASS
    return verdict, blockers, risk


def aggregate_risk(
    severity_weights: list[int],
    is_blocker: list[int],
    total_lines: int,
    *,
    force_python: bool = False,
) -> tuple[GateVerdict, int, int]:
    if _NATIVE_LIB is None or force_python:
        return python_aggregate_risk(severity_weights, is_blocker, total_lines)

    n = len(severity_weights)
    if n <= 0:
        return GateVerdict.PASS, 0, 0

    c_weights = (ctypes.c_int32 * n)(*(int(w) for w in severity_weights))
    c_blockers = (ctypes.c_int32 * n)(*(int(b) for b in is_blocker))
    out_blockers = ctypes.c_int32(0)
    out_risk = ctypes.c_int32(0)

    code = int(
        _NATIVE_LIB.slopguard_aggregate_risk(
            c_weights,
            c_blockers,
            n,
            int(total_lines),
            ctypes.byref(out_blockers),
            ctypes.byref(out_risk),
        )
    )
    return _VERDICT_MAP.get(code, GateVerdict.BLOCK), int(out_blockers.value), int(out_risk.value)

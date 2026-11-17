"""Deterministic showcase fixtures comparing AI slop against clean verified implementations."""

from __future__ import annotations

from pydantic import BaseModel

from slopguard.analyzers.gate_engine import scan_source
from slopguard.hooks.claude_hook import evaluate_claude_hook_payload
from slopguard.types import SlopReport

SLOPPY_PYTHON_SAMPLE = '''"""Unverified AI-generated payment webhook handler."""

from fastapi_quantum_shield import verify_signature  # Hallucinated package


def process_payout(account_id: str, amount_cents: int) -> dict[str, str]:
    """Transfer payout to recipient ledger."""
    try:
        if amount_cents <= 0:
            raise ValueError("Invalid payout")
        # TODO: stub implementation for brevity
        return {}
    except Exception:
        pass


def compute_dynamic_fee(formula: str) -> float:
    return float(eval(formula))
'''

CLEAN_PYTHON_SAMPLE = '''"""Verified deterministic payment webhook handler."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(secret: bytes, payload: bytes, expected_hex: str) -> bool:
    """Verify HMAC-SHA256 webhook signature in constant time."""
    digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected_hex)


def process_payout(account_id: str, amount_cents: int) -> dict[str, int | str]:
    """Validate and record integer payout allocation."""
    if not account_id.strip():
        raise ValueError("account_id is required")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    fee_cents = max(1, (amount_cents * 25 + 5000) // 10000)
    return {"account_id": account_id, "net_cents": amount_cents - fee_cents, "fee_cents": fee_cents}
'''

SLOPPY_TSX_SAMPLE = """import React from "react";

export function BillingCard() {
  return (
    <div className="card">
      <p>Lorem ipsum coming soon</p>
      <button onClick={() => {}}>Sync Invoice</button>
    </div>
  );
}
"""

CLEAN_TSX_SAMPLE = """import React, { useState } from "react";

export function BillingCard({ initialCount }: { initialCount: number }) {
  const [syncedCount, setSyncedCount] = useState(initialCount);
  return (
    <div className="card">
      <p>Synced invoices: {syncedCount}</p>
      <button onClick={() => setSyncedCount((c) => c + 1)}>Sync Invoice</button>
    </div>
  );
}
"""


class DemoShowcasePayload(BaseModel):
    sloppy_python: str
    clean_python: str
    sloppy_tsx: str
    clean_tsx: str
    sloppy_py_report: SlopReport
    clean_py_report: SlopReport
    sloppy_tsx_report: SlopReport
    clean_tsx_report: SlopReport
    claude_hook_exit_code: int
    claude_hook_decision: str
    claude_hook_reason: str


def build_demo_showcase() -> DemoShowcasePayload:
    sloppy_py = scan_source(SLOPPY_PYTHON_SAMPLE, file_path="src/payouts.py")
    clean_py = scan_source(CLEAN_PYTHON_SAMPLE, file_path="src/payouts.py")
    sloppy_ui = scan_source(SLOPPY_TSX_SAMPLE, file_path="ui/BillingCard.tsx")
    clean_ui = scan_source(CLEAN_TSX_SAMPLE, file_path="ui/BillingCard.tsx")
    exit_code, hook_resp = evaluate_claude_hook_payload(
        {
            "tool_input": {
                "file_path": "src/payouts.py",
                "content": SLOPPY_PYTHON_SAMPLE,
            }
        }
    )
    return DemoShowcasePayload(
        sloppy_python=SLOPPY_PYTHON_SAMPLE,
        clean_python=CLEAN_PYTHON_SAMPLE,
        sloppy_tsx=SLOPPY_TSX_SAMPLE,
        clean_tsx=CLEAN_TSX_SAMPLE,
        sloppy_py_report=sloppy_py,
        clean_py_report=clean_py,
        sloppy_tsx_report=sloppy_ui,
        clean_tsx_report=clean_ui,
        claude_hook_exit_code=exit_code,
        claude_hook_decision=str(hook_resp["decision"]),
        claude_hook_reason=str(hook_resp["reason"]),
    )

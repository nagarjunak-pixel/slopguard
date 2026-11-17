# Security Policy

## Reporting a Vulnerability

Please report security findings privately to `sendemailtonagarjuna@gmail.com` with subject `[SECURITY] slopguard`.

## Safe Static Analysis Guarantees
- `slopguard` never executes scanned code (`ast.parse` + C++20 byte scanning only; optional module lookup uses `importlib.util.find_spec` safely when opted in, never importing untrusted modules).
- All scans and Claude Code hooks execute 100% locally offline.

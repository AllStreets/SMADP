# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's
[private vulnerability reporting](https://github.com/AllStreets/SMADP/security/advisories/new)
or by emailing connorevans29@gmail.com.

We will acknowledge within 72 hours and aim to patch within 14 days. Please do
not open a public issue for security problems.

## Operator notes

- The catalog operator gate and the API write-endpoint auth are documented in
  [docs/SECURITY-NOTES.md](docs/SECURITY-NOTES.md). The public catalog
  (`catalog/verdicts/`) is only reachable through operator approval of pending
  items.
- The API (`smadp serve`) binds to loopback. Write endpoints require an
  operator bearer token (`SMADP_API_TOKEN`); without one configured they
  return 503. Do not expose the API publicly.

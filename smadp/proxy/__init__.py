"""Operator-run, local, opt-in MCP recording proxy (Pillar S3.1).

A stdio man-in-the-middle that wraps an agent's configured MCP server
command, relaying every byte unmodified while recording each JSON-RPC
message (secrets redacted, content-addressed). Recordings synthesize a
``behavior-observed`` runtime profile that passes through the operator
gate before it can influence any published verdict.
"""

"""Sanity test: /api/refresh is mounted on the main app."""

from __future__ import annotations

from smadp.api.server import create_app


def test_refresh_router_is_mounted() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
    assert "/api/refresh" in paths

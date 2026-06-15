"""Sanity test: /api/refresh is mounted on the main app."""

from __future__ import annotations

from smadp.api.server import create_app


def test_refresh_router_is_mounted() -> None:
    app = create_app()
    # Read mounted paths from the OpenAPI schema rather than iterating raw
    # route objects: newer Starlette keeps include_router results as
    # `_IncludedRouter` entries in `app.routes` that have no `.path`, so the
    # old `{route.path for ...}` comprehension raised AttributeError.
    paths = app.openapi().get("paths", {})
    assert "/api/refresh" in paths

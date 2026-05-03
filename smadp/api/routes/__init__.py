"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chronicle,
    evaluate,
    frameworks,
    health,
    meta,
    passports,
    sandbox,
    search,
    submit,
    transparency,
    verdicts,
    workspaces,
)

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    verdicts.router,
    submit.router,
    evaluate.router,
    search.router,
    frameworks.router,
    chronicle.router,
    sandbox.router,
    workspaces.router,
    transparency.router,
    passports.router,
]

__all__ = ["ROUTERS"]

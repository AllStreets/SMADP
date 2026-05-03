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
from smadp.webhooks import api as webhooks

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
    webhooks.router,
]

__all__ = ["ROUTERS"]

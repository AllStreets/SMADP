"""FastAPI route modules for the SMADP REST API."""

from smadp.api.routes import (
    agents,
    chains,
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
from smadp.refresh import api as refresh
from smadp.vendor import api as vendor
from smadp.webhooks import api as webhooks

ROUTERS = [
    health.router,
    meta.router,
    agents.router,
    chains.router,
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
    vendor.router,
    webhooks.router,
    refresh.router,
]

__all__ = ["ROUTERS"]

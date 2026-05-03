"""Native integration adapters: vanta, drata, slack."""

from smadp.integrations import drata, generic, slack, vanta  # noqa: F401
from smadp.integrations.base import Adapter, get_adapter, register_adapter

__all__ = ["Adapter", "get_adapter", "register_adapter"]

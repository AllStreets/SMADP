"""Native integration adapters: vanta, drata, slack."""

from smadp.integrations import generic  # noqa: F401  - registration side-effect
from smadp.integrations.base import Adapter, get_adapter, register_adapter

__all__ = ["Adapter", "get_adapter", "register_adapter"]

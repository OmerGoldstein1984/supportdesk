"""Pure-Python shim for the blocked `ormsgpack` extension.

This environment's application-control policy blocks the compiled ``ormsgpack``
extension that LangGraph's ``JsonPlusSerializer`` imports. LangGraph fully
supports a JSON fallback, so we shim ``ormsgpack`` to force that path:
``packb`` raises ``MsgpackEncodeError`` (message mentions "valid UTF-8"), which
makes ``JsonPlusSerializer`` fall back to extended JSON. Nothing is ever stored
as raw msgpack in this project, so ``unpackb`` is not reached in practice.
"""

from __future__ import annotations

from typing import Any


class MsgpackEncodeError(Exception):
    pass


class Ext:
    """Placeholder mirroring ormsgpack.Ext (never constructed at runtime here)."""

    def __init__(self, code: int, data: bytes):
        self.code = code
        self.data = data


# ormsgpack option flags. Values are arbitrary bitmasks; they are only combined
# into LangGraph's internal ``_option`` mask, which the shim ignores.
OPT_NON_STR_KEYS = 1
OPT_PASSTHROUGH_DATACLASS = 2
OPT_PASSTHROUGH_DATETIME = 4
OPT_PASSTHROUGH_ENUM = 8
OPT_PASSTHROUGH_UUID = 16


def packb(data: Any, default: Any = None, option: int = 0) -> Any:
    """Force the JSON fallback by always failing to encode."""
    raise MsgpackEncodeError("forcing JSON fallback (valid UTF-8)")


def unpackb(data: Any, *args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError("ormsgpack shim: unpackb unused (JSON fallback active)")

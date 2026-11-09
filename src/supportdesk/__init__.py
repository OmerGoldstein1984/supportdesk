"""SupportDesk package."""

import sys

# Shim for `ormsgpack`, a compiled extension blocked by this environment's
# application-control policy. LangGraph's `JsonPlusSerializer` imports it at
# module load time; registering this pure-Python shim first forces LangGraph's
# JSON checkpoint fallback (which LangGraph fully supports). See
# `supportdesk/_ormsgpack_shim.py`.
if "ormsgpack" not in sys.modules:  # pragma: no cover - environment shim
    from . import _ormsgpack_shim as _ormsgpack_shim  # noqa: F401

    sys.modules["ormsgpack"] = _ormsgpack_shim

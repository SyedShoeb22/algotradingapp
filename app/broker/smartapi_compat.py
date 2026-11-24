"""Compatibility adapter for Angel One SmartWebSocketV2 with websocket-client >= 1.0.

websocket-client >= 1.0 passes (wsapp, close_status_code, close_reason) to the on_close
callback. In smartapi-python 1.5.5, SmartWebSocketV2._on_close was declared with only
(self, wsapp), causing a TypeError at runtime when the connection is closed.

This module patches SmartWebSocketV2 in application code (without modifying site-packages)
using inspect.signature to safely inspect and adapt callback arguments BEFORE invoking them,
eliminating broad TypeError fallback loops and fragile traceback heuristics.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PATCHED = False


def _safe_dispatch(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Inspect callback signature and invoke with matching arguments once.
    
    Guarantees:
    - Never invokes callback more than once.
    - An internal TypeError or any other exception raised by the callback
      itself is logged and NOT retried.
    - Slices positional arguments if callback does not accept variadic (*args).
    - Filters keyword arguments if callback does not accept variadic (**kwargs).
    """
    if not callable(callback):
        return None

    sig = None
    try:
        sig = inspect.signature(callback)
    except (ValueError, TypeError):
        pass

    if sig is None:
        # inspect.signature failed (e.g. built-in or C-extension): call directly once
        return callback(*args, **kwargs)

    has_var_pos = any(
        p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()
    )
    has_var_kw = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )

    if has_var_pos and has_var_kw:
        # Accepts (*args, **kwargs): pass directly
        return callback(*args, **kwargs)

    pos_params = [
        p for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]

    # Limit args to accepted parameter count if no *args
    dispatched_args = args if has_var_pos else args[: len(pos_params)]

    # Filter kwargs if no **kwargs
    if has_var_kw:
        dispatched_kwargs = kwargs
    else:
        dispatched_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

    return callback(*dispatched_args, **dispatched_kwargs)


def apply_smartapi_websocket_patch() -> bool:
    """Safely patch SmartWebSocketV2 to tolerate variadic callback signatures."""
    global _PATCHED
    if _PATCHED:
        return True

    try:
        from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    except ImportError:
        logger.debug("SmartApi.smartWebSocketV2 is not installed; skipping patch.")
        return False

    original_on_close = getattr(SmartWebSocketV2, "_on_close", None)
    original_on_error = getattr(SmartWebSocketV2, "_on_error", None)

    def _safe_on_close(self: Any, wsapp: Any, *args: Any, **kwargs: Any) -> None:
        """Accept variadic close arguments and forward safely to application on_close."""
        callback = getattr(self, "on_close", None)
        if callback and callable(callback):
            try:
                _safe_dispatch(callback, wsapp, *args, **kwargs)
            except Exception as exc:
                logger.error("Error in on_close callback: %s", exc, exc_info=True)

    def _safe_on_error(self: Any, wsapp_or_reason: Any, *args: Any, **kwargs: Any) -> None:
        """Forward on_error safely to original _on_error or application callback."""
        if original_on_error and callable(original_on_error):
            try:
                _safe_dispatch(original_on_error, self, wsapp_or_reason, *args, **kwargs)
            except Exception as exc:
                logger.error("Error in SmartWebSocketV2._on_error: %s", exc, exc_info=True)

    SmartWebSocketV2._on_close = _safe_on_close
    if original_on_error:
        SmartWebSocketV2._on_error = _safe_on_error

    _PATCHED = True
    logger.info("SmartWebSocketV2 compatibility patch applied.")
    return True

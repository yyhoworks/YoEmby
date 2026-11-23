"""Idle thread wakeup and Python GIL churn reduction for CoreELEC."""

import threading
import time

from ce_opt import config

ShutdownEvent = threading.Event()


def notify_shutdown():
    """Immediately wake all threads waiting in ``interruptible_sleep``."""
    ShutdownEvent.set()


def reset_shutdown():
    """Reset shutdown event (primarily for unit tests)."""
    ShutdownEvent.clear()


def get_interval(config_key, upstream_default):
    """Return CoreELEC-tuned polling interval when enabled, else upstream default."""
    if not config.is_enabled("IDLE_WAKEUP_OPT"):
        return float(upstream_default)
    try:
        val = float(config.get_value(config_key, upstream_default))
        return val if val > 0 else float(upstream_default)
    except Exception:
        return float(upstream_default)


def interruptible_sleep(seconds, is_shutdown_fn, fallback_sleep_fn=None):
    """Event-backed replacement for upstream's 10Hz ``xbmc.sleep(100)`` loop.

    Wakes instantly when ``notify_shutdown()`` is signalled, and otherwise wakes
    at most once per ``IDLE_SLEEP_CHUNK_SEC`` (default 1.0s) to check
    ``is_shutdown_fn()`` in case shutdown was set without calling ``notify_shutdown``.
    Returns True if shutdown was requested, False if full sleep elapsed.
    """
    if is_shutdown_fn() or ShutdownEvent.is_set():
        return True

    if seconds <= 0:
        return False

    if not config.is_enabled("IDLE_WAKEUP_OPT"):
        if seconds < 0.1:
            if fallback_sleep_fn is not None:
                fallback_sleep_fn(int(seconds * 1000))
            else:
                time.sleep(seconds)
            return bool(is_shutdown_fn())

        for _ in range(int(seconds * 10)):
            if is_shutdown_fn():
                return True
            if fallback_sleep_fn is not None:
                fallback_sleep_fn(100)
            else:
                time.sleep(0.1)
        return False

    chunk_sec = max(0.1, float(config.get_value("IDLE_SLEEP_CHUNK_SEC", 1.0)))
    deadline = time.monotonic() + float(seconds)

    while True:
        if is_shutdown_fn() or ShutdownEvent.is_set():
            return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False

        if ShutdownEvent.wait(timeout=min(remaining, chunk_sec)):
            return True

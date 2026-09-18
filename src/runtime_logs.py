"""In-memory execution log shared by the server launcher and App Logs."""

from __future__ import annotations

from collections import deque
import logging
from threading import Lock


_MAX_EXECUTION_LOG_ENTRIES = 2_000
_execution_log_entries: deque[str] = deque(maxlen=_MAX_EXECUTION_LOG_ENTRIES)
_execution_log_lock = Lock()


class ExecutionLogHandler(logging.Handler):
    """Retain formatted server output so it can be inspected from the UI."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record).rstrip()
        except Exception:  # pragma: no cover - logging must never break the server.
            self.handleError(record)
            return
        if not message:
            return
        with _execution_log_lock:
            _execution_log_entries.append(message)


def execution_log_entries() -> list[str]:
    """Return a stable oldest-first snapshot of this process' server log."""
    with _execution_log_lock:
        return list(_execution_log_entries)

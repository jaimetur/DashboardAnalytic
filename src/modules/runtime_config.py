from __future__ import annotations

import os


IGNORE_EVENT_TIME_FILTERING_ENV = 'IGNORE_EVENT_TIME_FILTERING'


def env_flag(name: str, default: bool = False) -> bool:
    value = str(os.environ.get(name, '')).strip().casefold()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'on'}


def ignore_event_time_filtering() -> bool:
    """Return whether filters based on normalized event timestamps are disabled."""
    return env_flag(IGNORE_EVENT_TIME_FILTERING_ENV)

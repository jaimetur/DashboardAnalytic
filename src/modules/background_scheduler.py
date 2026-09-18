"""FIFO scheduler shared by application-owned background work."""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from threading import Condition, Thread
from typing import Any, Callable


class BackgroundTaskScheduler:
    """Run queued callables in submission order with a configurable concurrency cap."""

    def __init__(self, max_workers: int = 1, thread_name_prefix: str = 'background-task') -> None:
        self._condition = Condition()
        self._pending: deque[tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = deque()
        self._active = 0
        self._max_workers = max(1, int(max_workers))
        self._thread_name_prefix = thread_name_prefix
        self._workers: list[Thread] = []
        self._closed = False
        self._ensure_workers()

    def configure(self, max_workers: int) -> None:
        """Apply a new cap without interrupting queued or active work."""
        with self._condition:
            self._max_workers = max(1, int(max_workers))
            self._ensure_workers()
            self._condition.notify_all()

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def submit(self, callback: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError('The background task scheduler has been shut down.')
            self._pending.append((future, callback, args, kwargs))
            self._condition.notify_all()
        return future

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._condition:
            self._closed = True
            if cancel_futures:
                while self._pending:
                    self._pending.popleft()[0].cancel()
            self._condition.notify_all()
            workers = list(self._workers)
        if wait:
            for worker in workers:
                worker.join()

    def _ensure_workers(self) -> None:
        while len(self._workers) < self._max_workers:
            worker = Thread(
                target=self._run, name=f'{self._thread_name_prefix}-{len(self._workers) + 1}', daemon=True,
            )
            self._workers.append(worker)
            worker.start()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._closed and (not self._pending or self._active >= self._max_workers):
                    self._condition.wait()
                if self._closed and not self._pending:
                    return
                future, callback, args, kwargs = self._pending.popleft()
                if not future.set_running_or_notify_cancel():
                    continue
                self._active += 1
            try:
                future.set_result(callback(*args, **kwargs))
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                with self._condition:
                    self._active -= 1
                    self._condition.notify_all()

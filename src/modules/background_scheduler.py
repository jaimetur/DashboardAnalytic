"""Priority-aware scheduler shared by application-owned background work."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from contextlib import contextmanager
from threading import Condition, Thread
from typing import Any, Callable


@dataclass
class _ScheduledTask:
    future: Future[Any]
    callback: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    workspace_key: str | None = None
    priority: tuple[int, ...] = (0, 0)
    sequence: int = field(default=0)


class BackgroundTaskScheduler:
    """Run generic work FIFO and Workspace work by phase and dataset ID."""

    def __init__(self, max_workers: int = 1, thread_name_prefix: str = 'background-task') -> None:
        self._condition = Condition()
        self._pending: list[_ScheduledTask] = []
        self._active_workspaces: set[str] = set()
        self._sequence = 0
        self._active = 0
        self._dispatch_holds = 0
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

    @property
    def is_idle(self) -> bool:
        """Whether the scheduler has neither running nor queued work."""
        with self._condition:
            return self._active == 0 and not self._pending

    def submit(self, callback: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        return self.submit_ordered(callback, *args, **kwargs)

    def submit_ordered(
        self, callback: Callable[..., Any], /, *args: Any,
        workspace_key: str | None = None, priority: tuple[int, ...] = (0, 0),
        **kwargs: Any,
    ) -> Future[Any]:
        """Order workspace jobs by phase and ID while preserving FIFO ties."""
        future: Future[Any] = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError('The background task scheduler has been shut down.')
            self._sequence += 1
            self._pending.append(_ScheduledTask(
                future, callback, args, kwargs, workspace_key, priority, self._sequence,
            ))
            self._condition.notify_all()
        return future

    @contextmanager
    def defer_dispatch(self):
        """Queue a related batch atomically before a worker can start it."""
        with self._condition:
            self._dispatch_holds += 1
        try:
            yield
        finally:
            with self._condition:
                self._dispatch_holds -= 1
                self._condition.notify_all()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        with self._condition:
            self._closed = True
            if cancel_futures:
                while self._pending:
                    self._pending.pop().future.cancel()
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
                while True:
                    available = [
                        task for task in self._pending
                        if task.workspace_key is None or task.workspace_key not in self._active_workspaces
                    ]
                    if available and self._active < self._max_workers and not self._dispatch_holds:
                        break
                    if self._closed and not self._pending:
                        return
                    self._condition.wait()
                task = min(available, key=lambda item: (*item.priority, item.sequence))
                self._pending.remove(task)
                if not task.future.set_running_or_notify_cancel():
                    continue
                self._active += 1
                if task.workspace_key is not None:
                    self._active_workspaces.add(task.workspace_key)
            try:
                task.future.set_result(task.callback(*task.args, **task.kwargs))
            except BaseException as exc:
                task.future.set_exception(exc)
            finally:
                with self._condition:
                    self._active -= 1
                    if task.workspace_key is not None:
                        self._active_workspaces.discard(task.workspace_key)
                    self._condition.notify_all()

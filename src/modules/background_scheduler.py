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
    # Parallel Workspace work (such as processing one dataset) runs beside the other parallel work of its
    # Workspace, up to the worker cap; the rest of its Workspace work runs alone.
    parallel: bool = False


class BackgroundTaskScheduler:
    """Run generic work FIFO and Workspace work by phase and dataset ID."""

    def __init__(self, max_workers: int = 1, thread_name_prefix: str = 'background-task') -> None:
        self._condition = Condition()
        self._pending: list[_ScheduledTask] = []
        self._active_workspaces: dict[str, int] = {}
        self._exclusive_workspaces: set[str] = set()
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
        workspace_key: str | None = None, priority: tuple[int, ...] = (0, 0), parallel: bool = False,
        **kwargs: Any,
    ) -> Future[Any]:
        """Order workspace jobs by phase and ID while preserving FIFO ties."""
        future: Future[Any] = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError('The background task scheduler has been shut down.')
            self._sequence += 1
            self._pending.append(_ScheduledTask(
                future, callback, args, kwargs, workspace_key, priority, self._sequence, parallel,
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

    def _can_start(self, task: _ScheduledTask) -> bool:
        key = task.workspace_key
        if key is None:
            return True
        if task.parallel:
            # Never beside exclusive work, nor ahead of exclusive work of its Workspace that waits with a
            # better priority (such as rebuilding a combined table before the next datasets).
            return key not in self._exclusive_workspaces and not any(
                other.workspace_key == key and not other.parallel and (*other.priority, other.sequence) < (*task.priority, task.sequence)
                for other in self._pending
            )
        return key not in self._active_workspaces

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
                    available = [task for task in self._pending if self._can_start(task)]
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
                    self._active_workspaces[task.workspace_key] = self._active_workspaces.get(task.workspace_key, 0) + 1
                    if not task.parallel:
                        self._exclusive_workspaces.add(task.workspace_key)
            try:
                task.future.set_result(task.callback(*task.args, **task.kwargs))
            except BaseException as exc:
                task.future.set_exception(exc)
            finally:
                with self._condition:
                    self._active -= 1
                    if task.workspace_key is not None:
                        remaining = self._active_workspaces.get(task.workspace_key, 1) - 1
                        if remaining > 0:
                            self._active_workspaces[task.workspace_key] = remaining
                        else:
                            self._active_workspaces.pop(task.workspace_key, None)
                        if not task.parallel:
                            self._exclusive_workspaces.discard(task.workspace_key)
                    self._condition.notify_all()

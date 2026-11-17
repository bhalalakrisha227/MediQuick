"""
Background task abstraction.

Phase 0 ships an in-process thread pool so the project runs on plain Windows
with no Redis, Docker or Celery. Callers depend only on the TaskRunner
interface, so a real queue (Celery, RQ, ...) can replace ThreadPoolTaskRunner
later without changing OCR or other feature code.

Limits of the thread runner (by design, for development): jobs are lost if the
server restarts, and they do not scale across processes. From Phase 5, job
status will be persisted in MongoDB so the UI can show progress and retries.
"""
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class TaskRunner(ABC):
    @abstractmethod
    def submit(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        """Run func(*args, **kwargs) in the background and return a Future."""

    @abstractmethod
    def shutdown(self, wait: bool = True) -> None:
        """Release resources."""


class ThreadPoolTaskRunner(TaskRunner):
    def __init__(self, max_workers: int = 2):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mq-task")

    def submit(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self._executor.submit(func, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


_runner: TaskRunner | None = None


def get_task_runner() -> TaskRunner:
    """Return the shared runner chosen by the TASK_RUNNER setting."""
    global _runner
    if _runner is None:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured

        if settings.TASK_RUNNER != "thread":
            raise ImproperlyConfigured(
                f"Unknown TASK_RUNNER {settings.TASK_RUNNER!r}. Only 'thread' is available in Phase 0."
            )
        _runner = ThreadPoolTaskRunner(max_workers=settings.TASK_MAX_WORKERS)
    return _runner

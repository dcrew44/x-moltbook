"""Utility for enqueueing background tasks from async code."""

import logging
from typing import Any, Callable

from rq import Queue

from app.worker.redis_client import get_sync_redis

logger = logging.getLogger(__name__)

# Queue instances cache
_queues: dict[str, Queue] = {}


def get_queue(name: str = "default") -> Queue:
    """Get an RQ queue by name."""
    if name not in _queues:
        _queues[name] = Queue(name, connection=get_sync_redis())
    return _queues[name]


def enqueue_task(
    func: Callable,
    *args: Any,
    queue: str = "default",
    **kwargs: Any,
) -> str:
    """
    Enqueue a task for background processing.

    Args:
        func: The task function to call
        *args: Positional arguments to pass to the function
        queue: Queue name (default, high, or low)
        **kwargs: Keyword arguments to pass to the function

    Returns:
        Job ID string
    """
    q = get_queue(queue)
    job = q.enqueue(func, *args, **kwargs)
    logger.debug(f"Enqueued {func.__name__} on {queue} queue: {job.id}")
    return job.id

import logging
import os
import sys

from rq import Worker

from app.worker.config import QUEUES
from app.worker.redis_client import get_sync_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Run the RQ worker."""
    # Get queue selection from environment (empty = all queues)
    worker_queues_env = os.getenv("WORKER_QUEUES", "")

    if worker_queues_env:
        # Parse comma-separated queue names
        selected_queues = [q.strip() for q in worker_queues_env.split(",") if q.strip()]
        # Validate queue names
        invalid = set(selected_queues) - set(QUEUES)
        if invalid:
            logger.error(f"Invalid queue names: {invalid}. Valid queues: {QUEUES}")
            sys.exit(1)
    else:
        # Default: process all queues
        selected_queues = QUEUES

    logger.info(f"Starting worker with queues: {selected_queues}")

    redis_conn = get_sync_redis()
    worker = Worker(selected_queues, connection=redis_conn)

    worker.work()


if __name__ == "__main__":
    main()

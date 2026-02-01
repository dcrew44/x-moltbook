import logging
import sys

from redis import Redis
from rq import Worker

from app.worker.config import QUEUES, REDIS_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Run the RQ worker."""
    logger.info(f"Starting worker with queues: {QUEUES}")

    redis_conn = Redis.from_url(REDIS_URL)
    worker = Worker(QUEUES, connection=redis_conn)

    worker.work()


if __name__ == "__main__":
    main()

import os

from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

QUEUES = ["high", "default", "low"]

# Queue-specific settings for RQ
QUEUE_SETTINGS = {
    "high": {"timeout": 180},
    "default": {"timeout": 360},
    "low": {"timeout": 600},
}

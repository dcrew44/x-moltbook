"""Synchronous Redis client factory for RQ workers."""

import logging
import os
from typing import Union

from dotenv import load_dotenv
from redis import Redis
from redis.cluster import RedisCluster

load_dotenv()

logger = logging.getLogger(__name__)

SyncRedisClient = Union[Redis, RedisCluster]


def _parse_cluster_nodes(nodes_str: str) -> list[dict]:
    """Parse cluster nodes string into startup_nodes format."""
    nodes = []
    for node in nodes_str.split(","):
        node = node.strip()
        if not node:
            continue
        if ":" in node:
            host, port = node.rsplit(":", 1)
            nodes.append({"host": host, "port": int(port)})
        else:
            nodes.append({"host": node, "port": 6379})
    return nodes


def get_sync_redis() -> SyncRedisClient:
    """
    Get a synchronous Redis client (cluster or standalone based on config).

    Returns cluster client if REDIS_CLUSTER_ENABLED=true and REDIS_CLUSTER_NODES is set,
    otherwise returns standalone Redis client using REDIS_URL.
    """
    cluster_enabled = os.getenv("REDIS_CLUSTER_ENABLED", "false").lower() == "true"
    cluster_nodes = os.getenv("REDIS_CLUSTER_NODES", "")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    if cluster_enabled and cluster_nodes:
        startup_nodes = _parse_cluster_nodes(cluster_nodes)
        logger.info(f"Worker connecting to Redis Cluster with {len(startup_nodes)} nodes")
        return RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=True,
        )
    else:
        logger.info("Worker connecting to standalone Redis")
        return Redis.from_url(redis_url, decode_responses=True)

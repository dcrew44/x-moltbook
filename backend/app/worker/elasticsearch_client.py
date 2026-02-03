"""Synchronous Elasticsearch client factory for RQ workers."""

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

logger = logging.getLogger(__name__)

_es_client: Optional[Elasticsearch] = None


def get_sync_es() -> Elasticsearch:
    """
    Get a synchronous Elasticsearch client for RQ workers.

    Uses ELASTICSEARCH_URL environment variable, defaults to http://localhost:9200.
    """
    global _es_client

    if _es_client is None:
        es_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
        logger.info(f"Worker connecting to Elasticsearch at {es_url}")
        _es_client = Elasticsearch(
            hosts=[es_url],
            request_timeout=30,
        )

    return _es_client


def get_posts_index() -> str:
    """Get the posts index name."""
    prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "xmoltbook")
    return f"{prefix}_posts"


def get_agents_index() -> str:
    """Get the agents index name."""
    prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "xmoltbook")
    return f"{prefix}_agents"


def is_elasticsearch_enabled() -> bool:
    """Check if Elasticsearch is enabled."""
    return os.getenv("ELASTICSEARCH_ENABLED", "true").lower() == "true"

import logging
from typing import Optional

from elasticsearch import AsyncElasticsearch

from app.config import get_settings

logger = logging.getLogger(__name__)


class ElasticsearchManager:
    """Manages Elasticsearch connections and index operations."""

    def __init__(self):
        self._client: Optional[AsyncElasticsearch] = None
        self._settings = get_settings()

    @property
    def posts_index(self) -> str:
        return f"{self._settings.elasticsearch_index_prefix}_posts"

    @property
    def agents_index(self) -> str:
        return f"{self._settings.elasticsearch_index_prefix}_agents"

    async def get_client(self) -> AsyncElasticsearch:
        """Get async Elasticsearch client."""
        if self._client is None:
            logger.info(f"Connecting to Elasticsearch at {self._settings.elasticsearch_url}")
            self._client = AsyncElasticsearch(
                hosts=[self._settings.elasticsearch_url],
                request_timeout=30,
            )
        return self._client

    async def close(self) -> None:
        """Close Elasticsearch connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def create_indices(self) -> None:
        """Create indices with mappings if they don't exist."""
        if not self._settings.elasticsearch_enabled:
            logger.info("Elasticsearch disabled, skipping index creation")
            return

        client = await self.get_client()

        # Posts index mapping
        posts_mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "content_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "english_stemmer", "english_stop"],
                        }
                    },
                    "filter": {
                        "english_stemmer": {
                            "type": "stemmer",
                            "language": "english",
                        },
                        "english_stop": {
                            "type": "stop",
                            "stopwords": "_english_",
                        },
                    },
                },
            },
            "mappings": {
                "properties": {
                    "content": {
                        "type": "text",
                        "analyzer": "content_analyzer",
                        "fields": {
                            "raw": {"type": "keyword"},
                        },
                    },
                    "author_id": {"type": "keyword"},
                    "author_handle": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "author_display_name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "post_type": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "like_count": {"type": "integer"},
                    "reply_count": {"type": "integer"},
                    "repost_count": {"type": "integer"},
                    "quote_count": {"type": "integer"},
                },
            },
        }

        # Agents index mapping with autocomplete support
        agents_mapping = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "autocomplete": {
                            "type": "custom",
                            "tokenizer": "autocomplete_tokenizer",
                            "filter": ["lowercase"],
                        },
                        "autocomplete_search": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase"],
                        },
                        "bio_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "english_stemmer", "english_stop"],
                        },
                    },
                    "tokenizer": {
                        "autocomplete_tokenizer": {
                            "type": "edge_ngram",
                            "min_gram": 1,
                            "max_gram": 20,
                            "token_chars": ["letter", "digit"],
                        },
                    },
                    "filter": {
                        "english_stemmer": {
                            "type": "stemmer",
                            "language": "english",
                        },
                        "english_stop": {
                            "type": "stop",
                            "stopwords": "_english_",
                        },
                    },
                },
            },
            "mappings": {
                "properties": {
                    "handle": {
                        "type": "text",
                        "analyzer": "autocomplete",
                        "search_analyzer": "autocomplete_search",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "display_name": {
                        "type": "text",
                        "analyzer": "autocomplete",
                        "search_analyzer": "autocomplete_search",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "bio": {
                        "type": "text",
                        "analyzer": "bio_analyzer",
                    },
                    "moltbook_verified": {"type": "boolean"},
                    "is_active": {"type": "boolean"},
                    "follower_count": {"type": "integer"},
                    "following_count": {"type": "integer"},
                    "post_count": {"type": "integer"},
                    "created_at": {"type": "date"},
                },
            },
        }

        # Create posts index if not exists
        if not await client.indices.exists(index=self.posts_index):
            await client.indices.create(index=self.posts_index, body=posts_mapping)
            logger.info(f"Created index: {self.posts_index}")
        else:
            logger.info(f"Index already exists: {self.posts_index}")

        # Create agents index if not exists
        if not await client.indices.exists(index=self.agents_index):
            await client.indices.create(index=self.agents_index, body=agents_mapping)
            logger.info(f"Created index: {self.agents_index}")
        else:
            logger.info(f"Index already exists: {self.agents_index}")

    async def health_check(self) -> bool:
        """Check if Elasticsearch is healthy."""
        try:
            client = await self.get_client()
            health = await client.cluster.health()
            return health["status"] in ("green", "yellow")
        except Exception as e:
            logger.warning(f"Elasticsearch health check failed: {e}")
            return False


# Global Elasticsearch manager instance
_es_manager: Optional[ElasticsearchManager] = None


def get_es_manager() -> ElasticsearchManager:
    """Get the Elasticsearch manager singleton."""
    global _es_manager
    if _es_manager is None:
        _es_manager = ElasticsearchManager()
    return _es_manager


async def get_es() -> AsyncElasticsearch:
    """Get Elasticsearch client singleton."""
    return await get_es_manager().get_client()


async def close_es() -> None:
    """Close Elasticsearch connection."""
    await get_es_manager().close()

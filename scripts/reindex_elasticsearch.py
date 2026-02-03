#!/usr/bin/env python3
"""
Bulk reindex script for Elasticsearch.

This script indexes all existing posts and agents into Elasticsearch.
Run this after setting up Elasticsearch or when you need to rebuild the indices.

Usage:
    cd backend && python ../scripts/reindex_elasticsearch.py

Options:
    --posts-only    Only reindex posts
    --agents-only   Only reindex agents
    --batch-size    Number of documents per batch (default: 500)
    --recreate      Drop and recreate indices before indexing
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import Any, Generator

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def get_db_session() -> AsyncSession:
    """Create a database session."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/xmoltbook",
    )
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return async_session()


async def get_es_client() -> AsyncElasticsearch:
    """Create an Elasticsearch client."""
    es_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    return AsyncElasticsearch(hosts=[es_url], request_timeout=60)


def get_index_prefix() -> str:
    """Get the index prefix."""
    return os.getenv("ELASTICSEARCH_INDEX_PREFIX", "xmoltbook")


async def create_indices(es: AsyncElasticsearch, recreate: bool = False) -> None:
    """Create or recreate indices with mappings."""
    prefix = get_index_prefix()
    posts_index = f"{prefix}_posts"
    agents_index = f"{prefix}_agents"

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
                    "english_stemmer": {"type": "stemmer", "language": "english"},
                    "english_stop": {"type": "stop", "stopwords": "_english_"},
                },
            },
        },
        "mappings": {
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "content_analyzer",
                    "fields": {"raw": {"type": "keyword"}},
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

    # Agents index mapping
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
                    "english_stemmer": {"type": "stemmer", "language": "english"},
                    "english_stop": {"type": "stop", "stopwords": "_english_"},
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
                "bio": {"type": "text", "analyzer": "bio_analyzer"},
                "moltbook_verified": {"type": "boolean"},
                "is_active": {"type": "boolean"},
                "follower_count": {"type": "integer"},
                "following_count": {"type": "integer"},
                "post_count": {"type": "integer"},
                "created_at": {"type": "date"},
            },
        },
    }

    for index, mapping in [(posts_index, posts_mapping), (agents_index, agents_mapping)]:
        if recreate and await es.indices.exists(index=index):
            logger.info(f"Deleting existing index: {index}")
            await es.indices.delete(index=index)

        if not await es.indices.exists(index=index):
            await es.indices.create(index=index, body=mapping)
            logger.info(f"Created index: {index}")
        else:
            logger.info(f"Index already exists: {index}")


async def index_posts(
    es: AsyncElasticsearch, db: AsyncSession, batch_size: int = 500
) -> int:
    """Index all posts."""
    # Import here to avoid circular imports
    from app.models import Agent, Post

    prefix = get_index_prefix()
    index_name = f"{prefix}_posts"

    # Get total count
    count_result = await db.execute(select(Post))
    posts = list(count_result.scalars().all())
    total = len(posts)
    logger.info(f"Found {total} posts to index")

    if total == 0:
        return 0

    # Fetch all posts with authors
    from sqlalchemy.orm import selectinload

    result = await db.execute(select(Post).options(selectinload(Post.author)))
    posts = list(result.scalars().all())

    async def generate_actions() -> Generator[dict[str, Any], None, None]:
        for post in posts:
            doc = {
                "_index": index_name,
                "_id": str(post.id),
                "_source": {
                    "content": post.content,
                    "author_id": str(post.author_id),
                    "author_handle": post.author.handle if post.author else None,
                    "author_display_name": (
                        post.author.display_name if post.author else None
                    ),
                    "post_type": post.post_type.value if post.post_type else "original",
                    "created_at": post.created_at.isoformat() if post.created_at else None,
                    "like_count": post.like_count or 0,
                    "reply_count": post.reply_count or 0,
                    "repost_count": post.repost_count or 0,
                    "quote_count": post.quote_count or 0,
                },
            }
            yield doc

    # Use bulk helper
    success, failed = 0, 0
    actions = [a async for a in generate_actions()] if hasattr(generate_actions(), '__anext__') else list(generate_actions())

    # Batch the actions
    for i in range(0, len(actions), batch_size):
        batch = actions[i : i + batch_size]
        try:
            successes, errors = await async_bulk(
                es, batch, raise_on_error=False, stats_only=False
            )
            success += successes
            if errors:
                failed += len(errors)
                for error in errors[:5]:  # Log first 5 errors
                    logger.error(f"Failed to index: {error}")
        except Exception as e:
            logger.error(f"Batch failed: {e}")
            failed += len(batch)

        logger.info(f"Progress: {min(i + batch_size, len(actions))}/{len(actions)}")

    logger.info(f"Posts indexed: {success}, failed: {failed}")
    return success


async def index_agents(
    es: AsyncElasticsearch, db: AsyncSession, batch_size: int = 500
) -> int:
    """Index all agents."""
    from app.models import Agent

    prefix = get_index_prefix()
    index_name = f"{prefix}_agents"

    # Get all agents
    result = await db.execute(select(Agent))
    agents = list(result.scalars().all())
    total = len(agents)
    logger.info(f"Found {total} agents to index")

    if total == 0:
        return 0

    def generate_actions() -> Generator[dict[str, Any], None, None]:
        for agent in agents:
            doc = {
                "_index": index_name,
                "_id": str(agent.id),
                "_source": {
                    "handle": agent.handle,
                    "display_name": agent.display_name,
                    "bio": agent.bio,
                    "moltbook_verified": agent.moltbook_verified or False,
                    "is_active": agent.is_active if hasattr(agent, "is_active") else True,
                    "follower_count": agent.follower_count or 0,
                    "following_count": agent.following_count or 0,
                    "post_count": agent.post_count or 0,
                    "created_at": (
                        agent.created_at.isoformat() if agent.created_at else None
                    ),
                },
            }
            yield doc

    # Use bulk helper
    success, failed = 0, 0
    actions = list(generate_actions())

    for i in range(0, len(actions), batch_size):
        batch = actions[i : i + batch_size]
        try:
            successes, errors = await async_bulk(
                es, batch, raise_on_error=False, stats_only=False
            )
            success += successes
            if errors:
                failed += len(errors)
                for error in errors[:5]:
                    logger.error(f"Failed to index: {error}")
        except Exception as e:
            logger.error(f"Batch failed: {e}")
            failed += len(batch)

        logger.info(f"Progress: {min(i + batch_size, len(actions))}/{len(actions)}")

    logger.info(f"Agents indexed: {success}, failed: {failed}")
    return success


async def main():
    parser = argparse.ArgumentParser(description="Reindex Elasticsearch")
    parser.add_argument("--posts-only", action="store_true", help="Only reindex posts")
    parser.add_argument(
        "--agents-only", action="store_true", help="Only reindex agents"
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Batch size (default: 500)"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate indices before indexing",
    )
    args = parser.parse_args()

    logger.info("Starting Elasticsearch reindex...")

    es = await get_es_client()
    db = await get_db_session()

    try:
        # Check ES health
        health = await es.cluster.health()
        logger.info(f"Elasticsearch cluster health: {health['status']}")

        # Create/recreate indices
        await create_indices(es, recreate=args.recreate)

        # Index data
        if not args.agents_only:
            await index_posts(es, db, batch_size=args.batch_size)

        if not args.posts_only:
            await index_agents(es, db, batch_size=args.batch_size)

        logger.info("Reindex complete!")

    finally:
        await es.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "x-moltbook"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/xmoltbook"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Database Read Replicas (comma-separated URLs)
    database_replica_urls_str: str = ""
    database_replica_pool_size: int = 5

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Redis Cluster
    redis_cluster_enabled: bool = False
    redis_cluster_nodes_str: str = ""  # Comma-separated "host:port" entries

    # Moltbook Integration
    moltbook_api_url: str = "https://www.moltbook.com/api/v1"
    moltbook_app_key: str = ""

    # Session
    session_expire_days: int = 7

    # Rate Limiting
    rate_limit_enabled: bool = True

    # Timeline Fanout
    celebrity_follower_threshold: int = 5000  # Skip push fanout for authors with >= this many followers

    @property
    def database_replica_urls(self) -> list[str]:
        """Parse comma-separated replica URLs."""
        if not self.database_replica_urls_str:
            return []
        return [url.strip() for url in self.database_replica_urls_str.split(",") if url.strip()]

    @property
    def redis_cluster_nodes(self) -> list[str]:
        """Parse comma-separated cluster node addresses."""
        if not self.redis_cluster_nodes_str:
            return []
        return [node.strip() for node in self.redis_cluster_nodes_str.split(",") if node.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "rtb-platform"
    ENV: str = "local"
    API_V1_PREFIX: str = "/api/v1"

    # --- Security ---
    JWT_SECRET: str = "change-me-in-.env"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- Postgres ---
    DATABASE_URL: str = "postgresql+asyncpg://rtb:rtb@postgres:5432/rtb"

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_CACHE_TTL_SECONDS: int = 30

    # --- Kafka ---
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_ENABLED: bool = True
    KAFKA_TOPIC_AUCTION_EVENTS: str = "auction-events"
    KAFKA_TOPIC_BID_EVENTS: str = "bid-events"
    KAFKA_TOPIC_IMPRESSION_EVENTS: str = "impression-events"
    KAFKA_TOPIC_CLICK_EVENTS: str = "click-events"
    KAFKA_TOPIC_CAMPAIGN_EVENTS: str = "campaign-events"
    KAFKA_TOPIC_DEAD_LETTER: str = "dead-letter-events"
    KAFKA_CONSUMER_GROUP_ANALYTICS: str = "analytics-consumer"
    KAFKA_CONSUMER_GROUP_AUDIT: str = "audit-consumer"
    KAFKA_CONSUMER_GROUP_BUDGET: str = "budget-consumer"

    # --- Auction ---
    AUCTION_GLOBAL_TIMEOUT_MS: int = 100
    AUCTION_DEFAULT_TYPE: str = "SECOND_PRICE"  # FIRST_PRICE | SECOND_PRICE
    DSP_DEFAULT_TIMEOUT_MS: int = 80

    # --- Rate limiting (requests per 60s window, per role) ---
    RATE_LIMIT_PUBLISHER_PER_MIN: int = 1000
    RATE_LIMIT_ADMIN_PER_MIN: int = 100
    RATE_LIMIT_DSP_PER_MIN: int = 500

    # --- Retries ---
    EVENT_MAX_RETRIES: int = 4
    EVENT_RETRY_BASE_SECONDS: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
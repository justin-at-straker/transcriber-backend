from straker_utils.redis.asyncio import get_redis_auto


# Redis connection settings in .env file.
redis_conn = get_redis_auto()

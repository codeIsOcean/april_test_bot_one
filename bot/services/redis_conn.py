from redis.asyncio import Redis
import os
import logging

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

try:
    redis = Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

    async def test_connection():
        try:
            await redis.ping()
            logger.info(f"✅ Соединение с Redis ({REDIS_HOST}:{REDIS_PORT}) установлено")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Redis ({REDIS_HOST}:{REDIS_PORT}): {e}")

except Exception as e:
    logger.error(f"❌ Критическая ошибка Redis при инициализации: {e}")
    redis = None

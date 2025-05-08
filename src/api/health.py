from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging
from src.redis.redis_client import redis_conn

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/")
async def read_root():
    """
    Health check endpoint to verify the connection to Redis.
    """
    try:
        await redis_conn.ping()
        return JSONResponse(status_code=200, content={"status": "OK"})
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=500, content={"status": "Cannot connect to Redis"}
        )
import logging
import os
import asyncio
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import buglog # type: ignore
from dotenv import load_dotenv

from .config import settings
from .redis.redis_client import redis_conn
from .redis.redis_consumer import TranscriptionConsumer
from .utils.task import monitor_stuck_tasks

from .api.transcription_routes import router as transcription_router
from .api.health import router as health_router

# Convert log level string to logging constant
numeric_log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)

logging.basicConfig(
    level=numeric_log_level,
    format='%(asctime)s [%(levelname)s] [%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

buglog.init(
    listener=settings.BUGLOG_LISTENER_URL,
    app_name="sup-transcription-api",
    hostname="Transcriber API",
)

load_dotenv()

logger = logging.getLogger(__name__)

async def start_consumer():
    # Note: Only deviate from the defaults for testing purposes.
    consumer_group = os.getenv("REDIS_CONSUMER_GROUP") or "transcription"
    consumer_name = os.getenv("REDIS_CONSUMER") or "transcription_worker"

    # First test that the Redis connection is working.
    await redis_conn.ping()

    consumer = TranscriptionConsumer(
        redis_conn,
        consumer_group,
        consumer_name,
        streams=[
            "transcription:media:asr",
        ]
    )

    logger.info(
        "Started app with:\n"
        f"Consumer Group: {consumer_group}\n"
        f"Consumer: {consumer_name}\n"
    )

    try:
        await consumer.run()
    except Exception as e:
        buglog.notify_exception(
            e, extra={"consumer_group": consumer_group, "consumer": consumer_name}
        )
        logger.exception(f"App stopped due to an unhandled exception: {e}")
    except BaseException as e:
        logger.info(f"App stopped manually: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    consumer_task = asyncio.create_task(start_consumer())
    monitor_task = asyncio.create_task(monitor_stuck_tasks())
    logger.info("Consumer and monitoring tasks started.")
    yield
    # Shutdown code
    logger.info("Shutting down tasks...")
    consumer_task.cancel()
    monitor_task.cancel()
    try:
        await asyncio.gather(consumer_task, monitor_task, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("Tasks successfully cancelled.")
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Whisper Transcription Service",
    description="API for uploading audio/video files and receiving SRT transcriptions.",
    version="0.1.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transcription_router, prefix="/api", tags=["Transcription"])
app.include_router(health_router, prefix="/health", tags=["Health"])

@app.get("/", tags=["Root"])
async def read_root():
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Transcription Service API"}

if __name__ == "__main__":
    reload = os.getenv("RELOAD", "true").lower() == "true"
    workers = int(os.getenv("WORKERS", 1))
    uvicorn.run(
        app="app.main:app",
        host=settings.FASTAPI_HOST,
        port=settings.FASTAPI_PORT,
        reload=reload,
        workers=workers,
    ) 
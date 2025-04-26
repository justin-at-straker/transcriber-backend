import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import settings
from .config import settings
# Import the API router
from .api.transcription_routes import router as transcription_router

# --- Configuration & Setup ---
# pydantic-settings handles .env loading
# load_dotenv() # Removed

# --- Basic Logging Configuration ---
# Configure logging here so it's set up when the app starts
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(), # Use setting for log level
    format='%(asctime)s [%(levelname)s] [%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title=settings.APP_NAME, # Use setting for title
    description="API for uploading audio/video files and receiving SRT transcriptions.",
    version="0.1.0",
    debug=settings.DEBUG # Use setting for debug mode
)

# --- CORS Configuration ---
# Allow requests from configured origins
origins = settings.ALLOWED_ORIGINS

logger.info(f"Allowing CORS origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # Use setting for allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Include API Routers ---
# Include the transcription router with a prefix
app.include_router(transcription_router, prefix="/api", tags=["Transcription"])

# --- Root Endpoint (Optional) ---
@app.get("/", tags=["Root"])
async def read_root():
    logger.info("Root endpoint accessed.")
    return {"message": "Welcome to the Transcription Service API"}

# --- Uvicorn Runner (for direct execution, e.g., python -m app.main) ---
# Note: Uvicorn command needs to change now:
# python -m uvicorn app.main:app --reload --host <UVICORN_HOST> --port <UVICORN_PORT>
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server directly...")
    # Make sure to run this from the project root directory (transcribe-poc-backend)
    # Use settings for host and port
    uvicorn.run(
        "app.main:app",
        host=settings.UVICORN_HOST,
        port=settings.UVICORN_PORT,
        reload=settings.DEBUG, # Use debug setting for reload
        log_level=settings.LOG_LEVEL.lower()
    ) 
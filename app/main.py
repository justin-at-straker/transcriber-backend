import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Import the API router
from .api.transcription_routes import router as transcription_router

# --- Configuration & Setup ---
# Load .env file from the current directory (where app/main.py is, or its parent)
# Use find_dotenv=True if .env might be in parent dirs
load_dotenv() 

# --- Basic Logging Configuration ---
# Configure logging here so it's set up when the app starts
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] [%(name)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Transcription Service API",
    description="API for uploading audio/video files and receiving SRT transcriptions.",
    version="0.1.0"
)

# --- CORS Configuration ---
# Allow requests from the Vite frontend development server
# TODO: Restrict origins in production using environment variables
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # Or use os.getenv("ALLOWED_ORIGINS", "").split(",") for production
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
# python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 5175
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Uvicorn server directly...")
    # Make sure to run this from the project root directory (transcribe-poc-backend)
    uvicorn.run("app.main:app", host="0.0.0.0", port=5175, reload=True) 
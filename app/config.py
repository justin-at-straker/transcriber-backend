from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    # --- Core App Settings ---
    APP_NAME: str = "Transcribe POC Backend"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- OpenAI Settings ---
    OPENAI_API_KEY: str = "YOUR_OPENAI_API_KEY_HERE"  # REQUIRED
    WHISPER_MODEL: str = "whisper-1"
    OPENAI_API_LIMIT_MB: int = 24 # Actual API limit is 25MB, use slightly lower
    TARGET_CHUNK_SIZE_MB: int = 20 # Target size for audio chunks before splitting

    # --- CORS Settings ---
    # Comma-separated list of allowed origins
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Server Settings (for direct run) ---
    UVICORN_HOST: str = "0.0.0.0"
    UVICORN_PORT: int = 5175

    # --- External Dependencies ---
    # Optional: Specify path if ffmpeg is not in PATH
    FFMPEG_CMD: Optional[str] = None

    class Config:
        # Load settings from .env file
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

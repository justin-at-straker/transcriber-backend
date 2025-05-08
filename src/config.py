import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from straker_utils.domain import StrakerDomains
from straker_utils.environment import Environment
from pydantic import ValidationError
import sys

domains = StrakerDomains.from_environment()

class Settings(BaseSettings):
    """Application settings"""

    model_config = SettingsConfigDict(frozen=True)
    
    # Environment settings
    ENVIRONMENT: Environment
    FASTAPI_PORT: int
    FASTAPI_HOST: str
    DEBUG: bool
    LOG_LEVEL: str
    
    # Temp directory settings
    TEMP_DIR: str = os.getenv("TEMP_DIR", os.path.join(os.path.expanduser("~"), "whisper_transcriber_temp"))
    
    # Azure OpenAI settings
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"
    MODEL: str = "whisper-1"
    
    TARGET_CHUNK_SIZE_MB: int = 20
    OPENAI_API_LIMIT_MB: int = 25
    
    # File service settings
    FILE_SERVICE_API: str = os.getenv("FILE_SERVICE_API", "http://localhost:8001")
    
    # Buglog settings
    BUGLOG_LISTENER_URL: str = os.getenv("BUGLOG_LISTENER_URL", "")
    
    # Slack settings
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_CHANNEL_ID: str = os.getenv("SLACK_CHANNEL_ID", "")

try:
    settings = Settings()  # type: ignore
except ValidationError as e:
    print("Invalid configuration:")
    for error in e.errors():
        print(f'{error['loc']}: {error['msg']}')
    sys.exit(1)
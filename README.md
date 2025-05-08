# Transcription Service API

This project provides a FastAPI backend service that accepts audio or video file uploads, converts them to a suitable format, transcribes them using OpenAI's Whisper model, and returns the transcription in SRT format.

It includes handling for large files by automatically chunking the audio and processing the chunks in parallel before recombining the results.

## Features

* **Dual Operational Modes:**
  * **Direct API Upload:** Accepts audio/video file uploads via `POST /api/transcribe` for immediate processing and returns SRT directly.
  * **Asynchronous Task Processing:** Listens to Redis streams (e.g., `transcription:media:asr`) for transcription tasks. In this mode:
    * Downloads source audio/video from a URL (provided in the task message, typically via an external File Service).
    * Processes and transcribes the file.
    * Uploads the resulting SRT file to the File Service.
    * Publishes a notification with the results (including the SRT file ID) to a callback Redis stream.
* Accepts various audio/video file formats (via FFmpeg conversion).
* Uses FFmpeg to convert input files to 16kHz mono WAV format suitable for Whisper.
* Transcribes audio using the Azure OpenAI Whisper model (configurable via `MODEL` env var, defaults to `whisper-1`).
* Supports chunking for audio files exceeding the OpenAI API size limit (configurable via `OPENAI_API_LIMIT_MB`, defaults to 25MB).
  * Target chunk size is configurable via `TARGET_CHUNK_SIZE_MB` (defaults to 20MB).
* Processes chunks concurrently for faster transcription of large files.
* Optimized chunk transcription (uses in-memory data, avoids temporary chunk files).
* Handles initial FFmpeg conversion asynchronously (for the direct API upload route) to prevent blocking.
* Reassembles SRT results from chunks with accurate timestamp adjustments using the `srt` library.
* **Task State Tracking:** Records the status (Pending, Running, Success, Failed) and results of asynchronous tasks in a database.
* **Stuck Task Monitoring:** Periodically checks for tasks that are running for too long, marks them as failed, and can send notifications to Slack.
* Configurable via a `.env` file.
* Basic CORS setup for frontend development (e.g., `http://localhost:5173` - Note: current default is allow all `*`).

## Prerequisites

* **Python 3.10+** (as per `Pipfile`, though `Pipfile` specifies `3.12`)
* **FFmpeg:** Must be installed and in PATH. Verify with `ffmpeg -version`.
* **Redis:** Required for asynchronous task processing and health checks.
* **Database (MySQL recommended):**
  * A database server is needed for task state tracking. The application uses SQLAlchemy and is configured via `straker_utils` (which expects environment variables for DB connection pooling).
  * Specifically, a database (referred to as "sitecommons" in `src/utils/task.py`) needs a table named `transcriber_task_consumer_queue`.
  * **Table Schema (`transcriber_task_consumer_queue`):**
    * `obj_uuid` (VARCHAR, Primary Key) - Task UUID
    * `entry_id` (VARCHAR) - Redis stream entry ID
    * `event_name` (VARCHAR) - Source Redis stream name
    * `task_status` (VARCHAR) - e.g., Pending, Running, Success, Failed
    * `task_data` (JSON) - Original task data from Redis
    * `task_result` (JSON) - Result of the task (success data or error info)
    * `started_at` (DATETIME)
    * `finished_at` (DATETIME)
* **File Service (External):** For the asynchronous Redis-based workflow, this service expects to download source files from and upload result SRT files to an external file service. The API endpoint for this service must be configured.

## Setup

1. **Clone the repository (if applicable) or ensure you have the project files.**

2. **Navigate to the project root directory:**

    ```bash
    cd transcriber-backend
    ```

3. **Create and activate a Python virtual environment using Pipenv:**
    This command will also install all dependencies from the `Pipfile`.

    ```bash
    pipenv shell
    ```

    If you prefer to install dependencies separately, you can run:

    ```bash
    pipenv install --dev
    ```

    And then activate the shell with `pipenv shell`.

4. **Create a `.env` file** in the project root directory (`transcriber-backend/`) and add your Azure OpenAI API credentials and other necessary configurations:

    ```dotenv
    # Environment & App Settings
    ENVIRONMENT=local # e.g., local, development, production
    FASTAPI_PORT=9000
    FASTAPI_HOST=0.0.0.0
    DEBUG=True
    LOG_LEVEL=INFO # e.g., DEBUG, INFO, WARNING, ERROR

    # Azure OpenAI Settings
    AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
    AZURE_OPENAI_ENDPOINT=your_azure_openai_endpoint_here
    AZURE_OPENAI_API_VERSION=2024-02-15-preview # (Optional, defaults to this)
    MODEL=whisper-1                       # (Optional, defaults to this)

    # Transcription Settings
    TARGET_CHUNK_SIZE_MB=20 # (Optional, defaults to this)
    OPENAI_API_LIMIT_MB=25  # (Optional, defaults to this)
    TEMP_DIR=/tmp/whisper_transcriber_temp # (Optional, defaults to this path in user's home)

    # File Service (Required for Redis-based async tasks)
    FILE_SERVICE_API=http://your-file-service-api-endpoint # e.g., http://localhost:8001

    # Redis Consumer Settings (Optional, have defaults)
    # REDIS_CONSUMER_GROUP=transcription
    # REDIS_CONSUMER=transcription_worker

    # Buglog (Optional)
    # BUGLOG_LISTENER_URL=your_buglog_listener_url

    # Slack Notifications for Stuck Tasks (Optional)
    # SLACK_BOT_TOKEN=your_slack_bot_token_here
    # SLACK_CHANNEL_ID=your_slack_channel_id_here
    
    # Add other environment variables required by straker_utils for DB connections
    # e.g., DB_HOST_SCAFFOLD_SITECOMMONS, DB_USER_SCAFFOLD_SITECOMMONS, etc.
    ```

    *Ensure Redis connection details are also available in the environment if not localhost default (usually handled by `straker_utils` or `straker-redis-streams` underlying library configurations based on `ENVIRONMENT`).*

## Running the Application

Once the setup is complete, run the FastAPI application using Uvicorn from the project root directory. You can use the script defined in the `Pipfile`:

```bash
pipenv run api
```

Alternatively, you can run Uvicorn directly:

```bash
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 9000
```

* `src.main:app`: Tells Uvicorn where to find the FastAPI `app` instance (inside the `src` package, in the `main.py` file).
* `--reload`: Enables auto-reloading when code changes (useful for development).
* `--host 0.0.0.0`: Makes the server accessible on your network.
* `--port 9000`: Specifies the port to run on.

The API will be available at `http://localhost:9000` (or your machine's IP address on port 9000).
The Redis consumer for asynchronous tasks will also start.

## Running with Docker

This application can also be run using Docker and Docker Compose.

### Prerequisites for Docker

* **Docker:** Install Docker from [https://www.docker.com/get-started](https://www.docker.com/get-started).
* **Docker Compose:** Install Docker Compose (usually included with Docker Desktop). See [Docker documentation](https://docs.docker.com/compose/install/).
* **Shared Network/Volumes (for `docker-compose`):** The provided `docker-compose.yml` expects an external Docker network named `development_local-straker` and an external Docker volume named `development_data-dir`. If you don't have this shared Docker environment, you may need to create them or modify the `docker-compose.yml`:

    ```bash
    # Example: Create the external network if it doesn't exist
    docker network inspect development_local-straker >/dev/null 2>&1 || docker network create development_local-straker
    # Example: Create the external volume if it doesn't exist
    docker volume inspect development_data-dir >/dev/null 2>&1 || docker volume create development_data-dir
    ```

### Environment Setup

Ensure your `.env` file is correctly configured in the project root as described in the "Setup" section. The Docker setup will use this file for environment variables.

### Option 1: Using Docker Compose (Recommended)

The `docker-compose.yml` file is configured to build the Docker image and run the service.

1. **Start the service:**

    ```bash
    docker-compose up -d
    ```

    (Use `docker-compose up` to see logs in the foreground, or `docker-compose logs -f sup-transcription-api` to follow logs if detached).

2. The service will be accessible on the host at `http://localhost:9000` (port `9000` on host mapped to `80` in container).
3. The `src` directory is mounted into the container, so code changes should be reflected (Uvicorn runs with `--reload` as per the `Pipfile` script, which `docker-compose` typically uses if no specific command is set in compose, otherwise the Dockerfile CMD is used).
4. The `data-dir` volume is mounted at `/mnt/data` in the container. The application might use this path if the `TEMP_DIR` environment variable is set to `/mnt/data` or for interaction with a co-deployed file service.

### Option 2: Building and Running Manually with Docker

1. **Build the Docker image:**
    From the project root directory:

    ```bash
    docker build -t sup-transcription-api .
    ```

2. **Run the Docker container:**
    This is a more complex command as you need to manage networks, volumes, and environment variables manually.

    ```bash
    docker run -d --name local-sup-transcription-api \
        -p 9000:80 \
        --env-file .env \
        -v ./src:/app/src \
        -v /path/on/host/for/data-dir:/mnt/data \ # Example: mount a local directory to /mnt/data
        --network development_local-straker \     # Connect to the shared network
        sup-transcription-api
    ```

    * Replace `/path/on/host/for/data-dir` with an actual path on your host if you want to persist data or share it similarly to the `data-dir` volume in compose.
    * Ensure the container can reach Redis, Database, and the File Service, typically by connecting to the appropriate Docker network (like `development_local-straker`).
    * The default command in the `Dockerfile` is `["/venv/bin/python", "-m", "uvicorn", "src.main:app", "--proxy-headers", "--host", "0.0.0.0", "--port", "80"]`. If you need `--reload` for development with `docker run`, you would need to override the CMD or entrypoint.

## API Endpoints

### Root

* `GET /`
  * **Description:** A welcome message.
  * **Response:** `{"message": "Welcome to the Transcription Service API"}`

### Health Check

* `GET /health/`
  * **Description:** Checks the health of the service, primarily its ability to connect to Redis.
  * **Response (`200 OK`):** `{"status": "OK"}`
  * **Response (`500 Internal Server Error`):** `{"status": "Cannot connect to Redis"}`

### Transcription (Direct Upload)

* `POST /api/transcribe`
  * **Description:** Upload an audio or video file for direct, synchronous transcription.
  * **Request Body:** `multipart/form-data` containing the file.
    * `file`: The audio/video file to transcribe.
  * **Response (`200 OK`):** Returns the transcription in SRT format (`text/plain`) with a `Content-Disposition` header suggesting a filename like `original_filename.srt`.
  * **Response (`4XX/5XX Error`):** Returns JSON error details (e.g., missing API key, FFmpeg error, transcription failure).

### Asynchronous Transcription (via Redis)

This service also supports an asynchronous, event-driven workflow using Redis streams:

1. **Input:** A message is published to a configured Redis stream (e.g., `transcription:media:asr`). This message should contain `TranscriptionTaskData` (see `src/models/stream_event.py`), including:
    * `task_uuid`: A unique identifier for the task.
    * `download_url`: URL to the source audio/video file (accessible by this service).
    * `token`: Auth token if needed for the download URL.
    * `file_name`: Original name of the file.
    * `client_id`: Identifier for the client requesting transcription.
    * `callback_uri`: The Redis stream name where the result should be published.
    * Other fields like `tokens`, `symlink`.
2. **Processing:** The service's Redis consumer picks up the task:
    * Downloads the file.
    * Converts it to WAV.
    * Transcribes it (with chunking if needed).
    * Uploads the resulting SRT file to the configured File Service.
    * Updates task status in the database.
3. **Output:** A message is published to the `callback_uri` Redis stream. This message contains `StreamData` (see `src/models/stream_event.py`), including:
    * `task_uuid`
    * `client_id`
    * `file_id`: The ID of the uploaded SRT file in the File Service.
    * `file_name`: The name of the SRT file (e.g., `original_basename.srt`).
    * `source_file_name`
    * `error`: Error message if processing failed.

## Project Structure

```bash
transcriber-backend/
├── src/                # Main application package
│   ├── __init__.py
│   ├── api/            # API route definitions
│   │   ├── __init__.py
│   │   ├── transcription_routes.py # Handles /api/transcribe
│   │   └── health.py             # Handles /health
│   ├── services/       # Core business logic
│   │   ├── __init__.py
│   │   └── transcription_service.py # Transcription, chunking, Azure OpenAI client
│   ├── utils/          # Utility functions
│   │   ├── __init__.py
│   │   ├── ffmpeg_utils.py
│   │   ├── file_utils.py   # File download/upload to File Service
│   │   └── task.py         # Task state management (DB), stuck task monitor
│   ├── models/         # Pydantic and SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── stream_event.py # Pydantic models for Redis stream data
│   │   └── task.py         # SQLAlchemy model for TaskLog (DB table)
│   ├── tasks/          # Asynchronous task handling
│   │   ├── __init__.py
│   │   └── task_handler.py # Orchestrates processing for tasks from Redis
│   ├── redis/          # Redis integration
│   │   ├── __init__.py
│   │   ├── redis_client.py # Basic Redis connection
│   │   ├── redis_consumer.py # Consumes tasks from Redis streams
│   │   └── stream.py       # Utility for publishing to Redis streams
│   ├── config.py       # Application configuration (Pydantic BaseSettings)
│   ├── database.py     # Database engine pool setup (via straker_utils)
│   └── main.py         # FastAPI app creation, CORS, router inclusion, Redis consumer startup
├── .env                # Environment variables (local setup, ignored by git)
├── .gitignore          # Git ignore rules
├── Pipfile             # Pipenv dependencies
├── Pipfile.lock        # Pipenv lock file
├── README.md           # This file
# Removed requirements.txt from diagram as Pipfile is primary
```

*(Note: `straker_utils` and `straker-redis-streams` are key library dependencies providing common utilities for database, Redis, etc.)*

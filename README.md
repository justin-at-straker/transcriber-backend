# Transcription Service API

This project provides a FastAPI backend service that accepts audio or video file uploads, converts them to a suitable format, transcribes them using OpenAI's Whisper model, and returns the transcription in SRT format.

It includes handling for large files by automatically chunking the audio and processing the chunks in parallel before recombining the results.

## Features

*   Accepts various audio/video file formats.
*   Uses FFmpeg to convert input files to 16kHz mono WAV format suitable for Whisper.
*   Transcribes audio using the `whisper-1` model via the OpenAI API.
*   Supports chunking for audio files exceeding the OpenAI API size limit (25MB).
*   Processes chunks concurrently for faster transcription of large files.
*   Optimized chunk transcription (uses in-memory data, avoids temporary chunk files).
*   Handles initial FFmpeg conversion asynchronously to prevent blocking the server.
*   Reassembles SRT results from chunks with accurate timestamp adjustments.
*   Returns transcription results as an SRT file download.
*   Configurable via a `.env` file.
*   Basic CORS setup for frontend development (e.g., `http://localhost:5173`).

## Prerequisites

*   **Python 3.10+**
*   **FFmpeg:** The core audio/video conversion relies on FFmpeg. You must have FFmpeg installed and accessible in your system's PATH.
    *   Download and install from the official FFmpeg website: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
    *   Verify installation by running `ffmpeg -version` in your terminal.

## Setup

1.  **Clone the repository (if applicable) or ensure you have the project files.**

2.  **Navigate to the project root directory:**
    ```bash
    cd path/to/transcribe-poc-backend
    ```

3.  **Create and activate a Python virtual environment:**
    *   **Windows (PowerShell):**
        ```powershell
        python -m venv .venv
        .\.venv\Scripts\Activate.ps1
        ```
        *(Note: You might need to adjust your PowerShell execution policy if activation fails: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`)*
    *   **macOS/Linux:**
        ```bash
        python3 -m venv .venv
        source .venv/bin/activate
        ```

4.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Create a `.env` file** in the project root directory (`transcribe-poc-backend/`) and add your OpenAI API key:
    ```dotenv
    OPENAI_API_KEY=your_openai_api_key_here
    ```

## Running the Application

Once the setup is complete, run the FastAPI application using Uvicorn from the project root directory:

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 5175
```

*   `app.main:app`: Tells Uvicorn where to find the FastAPI `app` instance (inside the `app` package, in the `main.py` file).
*   `--reload`: Enables auto-reloading when code changes (useful for development).
*   `--host 0.0.0.0`: Makes the server accessible on your network.
*   `--port 5175`: Specifies the port to run on.

The API will be available at `http://localhost:5175` (or your machine's IP address on port 5175).

## API Endpoint

### `POST /api/transcribe`

*   **Description:** Upload an audio or video file for transcription.
*   **Request Body:** `multipart/form-data` containing the file.
    *   `file`: The audio/video file to transcribe.
*   **Response:**
    *   `200 OK`: Returns the transcription in SRT format (`text/plain`) with a `Content-Disposition` header suggesting a filename like `original_filename.srt`.
    *   `4XX/5XX Error`: Returns JSON error details if something goes wrong (e.g., missing API key, FFmpeg error, transcription failure).

## Project Structure

```
transcribe-poc-backend/
├── app/                # Main application package
│   ├── __init__.py
│   ├── api/            # API route definitions (FastAPI routers)
│   │   ├── __init__.py
│   │   └── transcription_routes.py
│   ├── services/       # Core business logic
│   │   ├── __init__.py
│   │   └── transcription_service.py
│   ├── utils/          # Utility functions (ffmpeg, file handling)
│   │   ├── __init__.py
│   │   ├── ffmpeg_utils.py
│   │   └── file_utils.py
│   └── main.py         # FastAPI app creation, CORS, router inclusion
├── .env                # Environment variables (ignored by git)
├── .gitignore          # Git ignore rules
├── README.md           # This file
└── requirements.txt    # Python dependencies
``` 
import os
import shutil
import tempfile
import logging
import asyncio
from pathlib import Path
from fastapi import APIRouter, UploadFile, HTTPException, File, BackgroundTasks
from fastapi.responses import PlainTextResponse

from ..config import settings
from ..services.transcription_service import (
    process_and_transcribe,
    TranscriptionError,
    OpenAIError,
    ChunkingError
)
from ..utils.ffmpeg_utils import convert_to_wav, FfmpegError

logger = logging.getLogger(__name__)
router = APIRouter()

# --- Transcription Endpoint ---
@router.post("/transcribe", response_class=PlainTextResponse)
async def transcribe_audio_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Accepts an audio/video file, processes it, transcribes, and returns SRT."""
    if not settings.AZURE_OPENAI_API_KEY:
        logger.error("AZURE_OPENAI_API_KEY is not configured in settings.")
        raise HTTPException(status_code=500, detail="Server configuration error: Missing API key.")

    logger.info("Received request on /api/transcribe")
    logger.info(f"Uploaded file details: filename='{file.filename}', content_type='{file.content_type}'")

    # Create a unique temporary directory for this request
    try:
        temp_dir_obj = tempfile.TemporaryDirectory()
        temp_dir = temp_dir_obj.name
        logger.info(f"Created temporary directory: {temp_dir}")
        # Schedule the entire directory cleanup
        background_tasks.add_task(temp_dir_obj.cleanup)
    except Exception as e:
        logger.error(f"Failed to create temporary directory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create temporary storage.")

    original_file_path = os.path.join(temp_dir, file.filename or "uploaded_file")
    converted_audio_path = None

    try:
        # 1. Save uploaded file temporarily
        logger.info(f"Saving uploaded file to: {original_file_path}")
        try:
            with open(original_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            logger.info("Saved uploaded file successfully.")
        except Exception as e:
            logger.error(f"Failed to save uploaded file {original_file_path}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

        # 2. Convert with FFmpeg
        base_filename = Path(file.filename or "output").stem
        # Use a safe filename and place it in the temp dir
        output_filename = f"{base_filename}_converted.wav"
        converted_audio_path = os.path.join(temp_dir, output_filename)

        try:
            # Run the blocking ffmpeg conversion in a separate thread
            await asyncio.to_thread(convert_to_wav, original_file_path, converted_audio_path)
        except FfmpegError as e:
             # Use the stderr from the custom exception if available
            detail = f"FFmpeg conversion failed: {e.stderr or e}"
            logger.error(f"FFmpeg error handled in route: {detail}")
            raise HTTPException(status_code=500, detail=detail)
        except Exception as e: # Catch any other unexpected error from convert_to_wav
             logger.error(f"Unexpected error during conversion call: {e}", exc_info=True)
             raise HTTPException(status_code=500, detail=f"Unexpected conversion error: {e}")

        # 3. Transcribe using the Service
        try:
            srt_content = await process_and_transcribe(converted_audio_path)
        except OpenAIError as e:
            logger.error(f"OpenAI error handled in route: Status={e.status_code} Message={e}")
            raise HTTPException(status_code=e.status_code or 500, detail=str(e))
        except (ChunkingError, TranscriptionError) as e:
            logger.error(f"Transcription/Chunking error handled in route: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception: # Catch unexpected errors from the service
             logger.exception("Unhandled error during transcription service call:")
             raise HTTPException(status_code=500, detail="An unexpected error occurred during transcription.")

        # 4. Return SRT Response
        logger.info("Sending SRT response...")
        original_base_name = Path(file.filename or "transcription").stem
        response_headers = {
            'Content-Disposition': f'attachment; filename="{original_base_name}.srt"'
        }
        return PlainTextResponse(content=srt_content or "", media_type='text/plain', headers=response_headers)

    except HTTPException as e:
        # Re-raise HTTPExceptions explicitly caught
        raise e
    except Exception:
        # Catch any unexpected errors during the overall process
        logger.exception("Unhandled error in /transcribe endpoint:")
        raise HTTPException(status_code=500, detail="An unexpected server error occurred.")
    # Note: The TemporaryDirectory cleanup happens automatically via background_tasks
    # even if exceptions occur, as long as the object was created. 
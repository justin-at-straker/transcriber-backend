import os
import shutil
import tempfile
import logging
import asyncio
import io
import math
from pathlib import Path
from datetime import timedelta
from fastapi import FastAPI, UploadFile, HTTPException, File, BackgroundTasks
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import openai
import ffmpeg
import srt
from pydub import AudioSegment
from openai import OpenAI

# --- Configuration & Setup ---
load_dotenv()

# --- Constants ---
OPENAI_API_LIMIT_MB = 24 # Use slightly less than 25MB limit
BYTES_PER_MB = 1024 * 1024
TARGET_CHUNK_SIZE_MB = 20 # Target size for each chunk

# Basic Logging (Consider using Winston equivalent like logging.config later if needed)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CORS Configuration ---
# Allow requests from the Vite frontend development server
# TODO: Restrict origins in production
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper Function for Cleanup ---
async def cleanup_temp_file(file_path: str):
    """Removes a temporary file, logging errors."""
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.info(f"Successfully deleted temp file: {file_path}")
    except OSError as e:
        logger.error(f"Failed to delete temp file {file_path}: {e}")

# --- Helper Function for Transcribing a Single Chunk ---
async def transcribe_chunk(client: OpenAI, audio_chunk_data: bytes, chunk_index: int, temp_dir: str) -> str:
    """Transcribes a single audio chunk and returns SRT content."""
    chunk_filename = f"chunk_{chunk_index}.wav"
    chunk_file_path = os.path.join(temp_dir, chunk_filename)
    logger.info(f"Processing chunk {chunk_index}: Saving to {chunk_file_path}")

    try:
        # Save chunk data to a temporary file
        with open(chunk_file_path, "wb") as f:
            f.write(audio_chunk_data)

        # Transcribe using OpenAI
        logger.info(f"Transcribing chunk {chunk_index}...")
        with open(chunk_file_path, "rb") as audio_file_handle:
            transcription_response = await asyncio.to_thread( # Run blocking call in thread
                client.audio.transcriptions.create,
                model="whisper-1",
                file=audio_file_handle,
                response_format="srt",
            )
        srt_content = transcription_response
        logger.info(f"Chunk {chunk_index} transcribed successfully.")
        return srt_content
    except openai.APIError as e:
        logger.error(f"OpenAI API Error for chunk {chunk_index}: Status={e.status_code}, Message={e.message}")
        # Propagate a meaningful error, maybe return None or raise specific exception
        return f"ERROR: Chunk {chunk_index} failed - {e.message}" # Or handle differently
    except Exception as e:
        logger.error(f"Error processing chunk {chunk_index}: {e}", exc_info=True)
        return f"ERROR: Chunk {chunk_index} failed unexpectedly." # Or handle differently
    finally:
        # Clean up the temporary chunk file
        await cleanup_temp_file(chunk_file_path)

# --- Transcription Endpoint ---
@app.post("/api/transcribe", response_class=PlainTextResponse)
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """Accepts an audio/video file, processes it, transcribes, and returns SRT."""
    logger.info("Received request on /api/transcribe")
    logger.info(f"Uploaded file details: filename='{file.filename}', content_type='{file.content_type}'")

    # Check for API Key early
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY is not set in the environment.")
        raise HTTPException(status_code=500, detail="Server configuration error: Missing API key.")

    # Use a temporary directory for robust handling
    with tempfile.TemporaryDirectory() as temp_dir:
        original_file_path = os.path.join(temp_dir, file.filename or "uploaded_file")
        converted_audio_path = None
        
        # Add files to be cleaned up at the end
        background_tasks.add_task(cleanup_temp_file, original_file_path)

        try:
            # 1. Save uploaded file temporarily
            logger.info(f"Saving uploaded file to: {original_file_path}")
            with open(original_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            logger.info("Saved uploaded file successfully.")

            # 2. Convert with FFmpeg (to WAV 16kHz mono)
            ffmpeg_start_time = logging.time.time() # Using logging time for simplicity
            base_filename = Path(file.filename or "output").stem
            output_filename = f"{base_filename}_{int(ffmpeg_start_time)}.wav"
            converted_audio_path = os.path.join(temp_dir, output_filename)
            background_tasks.add_task(cleanup_temp_file, converted_audio_path) # Add converted file for cleanup

            logger.info(f"Starting conversion to WAV: {original_file_path} -> {converted_audio_path}")
            try:
                (ffmpeg
                    .input(original_file_path)
                    .output(converted_audio_path, ar=16000, ac=1, sample_fmt='s16', vn=None) # ar=16k, ac=1, sample_fmt=s16, no video
                    .run(cmd=['ffmpeg', '-nostdin'], capture_stdout=True, capture_stderr=True, quiet=False) # Use quiet=False to see ffmpeg logs if needed
                )
            except ffmpeg.Error as e:
                stderr = e.stderr.decode('utf8') if e.stderr else 'N/A'
                logger.error(f"FFmpeg Error: {e} - Stderr: {stderr}")
                raise HTTPException(status_code=500, detail=f"FFmpeg conversion failed: {stderr}")
            
            ffmpeg_end_time = logging.time.time()
            logger.info(f"FFmpeg Conversion finished successfully in {ffmpeg_end_time - ffmpeg_start_time:.2f} s.")

            if not os.path.exists(converted_audio_path):
                raise HTTPException(status_code=500, detail="FFmpeg conversion finished but output file not found.")
            
            stats = os.stat(converted_audio_path)
            logger.info(f"Converted file size: {stats.st_size / (1024*1024):.2f} MB")

            # 3. Transcribe with OpenAI (Requesting SRT)
            logger.info(f"Attempting to transcribe converted file: {converted_audio_path} with model whisper-1 (requesting SRT)")
            openai_start_time = logging.time.time()
            client = OpenAI(api_key=api_key)

            if stats.st_size / BYTES_PER_MB < OPENAI_API_LIMIT_MB:
                # --- Simple Transcription (File size within limit) ---
                logger.info(f"File size ({stats.st_size / BYTES_PER_MB:.2f}MB) is within the limit. Using standard transcription.")
                try:
                    with open(converted_audio_path, "rb") as audio_file_handle:
                        transcription_response = client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file_handle,
                            response_format="srt",
                        )
                    srt_content = transcription_response
                except openai.APIError as e:
                    logger.error(f"OpenAI API Error: Status={e.status_code}, Message={e.message}")
                    raise HTTPException(status_code=e.status_code or 500, detail=f"OpenAI API Error: {e.message}")
                except Exception as e:
                    logger.error(f"Error during standard OpenAI call: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail="Transcription failed.")

            else:
                # --- Chunked Transcription (File size exceeds limit) ---
                logger.info(f"File size ({stats.st_size / BYTES_PER_MB:.2f}MB) exceeds limit ({OPENAI_API_LIMIT_MB}MB). Starting chunked transcription.")

                try:
                    logger.info("Loading audio file with pydub...")
                    audio = AudioSegment.from_wav(converted_audio_path)
                    logger.info(f"Audio duration: {audio.duration_seconds:.2f} seconds")

                    # Calculate chunk duration based on target size (approximate)
                    # This is a rough estimate as bitrate can vary slightly
                    bytes_per_second = stats.st_size / audio.duration_seconds
                    target_chunk_size_bytes = TARGET_CHUNK_SIZE_MB * BYTES_PER_MB
                    # Ensure chunk duration is at least 1 second to avoid tiny chunks
                    chunk_duration_ms = max(1000, int((target_chunk_size_bytes / bytes_per_second) * 1000))

                    num_chunks = math.ceil(audio.duration_seconds * 1000 / chunk_duration_ms)
                    logger.info(f"Splitting audio into {num_chunks} chunks of approx {chunk_duration_ms / 1000:.2f}s each.")

                    tasks = []
                    chunk_start_ms = 0
                    for i in range(num_chunks):
                        chunk_end_ms = min(chunk_start_ms + chunk_duration_ms, len(audio))
                        audio_chunk = audio[chunk_start_ms:chunk_end_ms]

                        # Export chunk to bytes in memory
                        buffer = io.BytesIO()
                        audio_chunk.export(buffer, format="wav")
                        buffer.seek(0)
                        chunk_data = buffer.read()

                        # Check chunk size before creating task (optional but good sanity check)
                        chunk_mb = len(chunk_data) / BYTES_PER_MB
                        if chunk_mb >= OPENAI_API_LIMIT_MB:
                             logger.warning(f"Chunk {i} size ({chunk_mb:.2f}MB) is too large, skipping (adjust TARGET_CHUNK_SIZE_MB).")
                             # Decide how to handle this - skip, raise error, etc.
                             # For now, we'll just skip creating a task for it.
                        else:
                            tasks.append(transcribe_chunk(client, chunk_data, i, temp_dir))

                        chunk_start_ms = chunk_end_ms
                        if chunk_start_ms >= len(audio):
                             break # Should not happen with ceil but safety break

                    if not tasks:
                        raise HTTPException(status_code=400, detail="No valid audio chunks could be generated.")

                    logger.info(f"Created {len(tasks)} transcription tasks. Running concurrently...")
                    results = await asyncio.gather(*tasks)
                    logger.info("All transcription tasks finished.")

                    # --- Combine SRT Results ---
                    all_subs = []
                    cumulative_offset = timedelta(seconds=0)
                    last_chunk_end = timedelta(seconds=0) # Track end time for accurate offset

                    for i, chunk_srt_content in enumerate(results):
                         if chunk_srt_content.startswith("ERROR:"):
                             logger.error(f"Skipping failed chunk {i}: {chunk_srt_content}")
                             # Need to estimate duration of failed chunk to maintain timing?
                             # Or accept potential time gap. Let's accept the gap for now.
                             # Estimate based on expected chunk duration
                             estimated_duration = timedelta(milliseconds=chunk_duration_ms)
                             cumulative_offset += estimated_duration
                             last_chunk_end = cumulative_offset # Assume it ended where it should have
                             continue # Skip processing this chunk's SRT

                         logger.info(f"Processing SRT for chunk {i}")
                         try:
                             chunk_subs = list(srt.parse(chunk_srt_content))
                             if not chunk_subs:
                                 logger.warning(f"Chunk {i} produced empty SRT content.")
                                 # Still need to advance offset based on expected chunk duration
                                 estimated_duration = timedelta(milliseconds=chunk_duration_ms)
                                 cumulative_offset = last_chunk_end + estimated_duration # Add expected duration
                                 last_chunk_end = cumulative_offset
                                 continue

                             # Important: Calculate offset based on the *actual* end time of the *previous* chunk's last subtitle
                             current_chunk_offset = last_chunk_end

                             # Adjust timestamps for the current chunk
                             for sub in chunk_subs:
                                 sub.start += current_chunk_offset
                                 sub.end += current_chunk_offset
                                 all_subs.append(sub)

                             # Update last_chunk_end for the next iteration using the end time of the last subtitle in *this* chunk
                             last_chunk_end = chunk_subs[-1].end
                             # Cumulative offset isn't strictly needed if we use last_chunk_end correctly
                             # cumulative_offset = last_chunk_end # Update cumulative offset

                         except Exception as parse_err:
                             logger.error(f"Failed to parse or process SRT for chunk {i}: {parse_err}", exc_info=True)
                             # How to handle? Skip? Estimate time? Let's skip and log.
                             estimated_duration = timedelta(milliseconds=chunk_duration_ms)
                             cumulative_offset = last_chunk_end + estimated_duration # Add expected duration
                             last_chunk_end = cumulative_offset

                    logger.info(f"Combining {len(all_subs)} subtitles from {len(tasks)} chunks.")
                    # Re-index subtitles sequentially
                    final_subs = srt.sort_and_reindex(all_subs)
                    srt_content = srt.compose(final_subs)

                except Exception as e:
                    logger.error(f"Error during chunked transcription process: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Chunked transcription failed: {e}")

            openai_end_time = logging.time.time()
            logger.info(f"OpenAI transcription process completed in {openai_end_time - openai_start_time:.2f} s.")
            # logger.info(f"Final Combined SRT Response: {srt_content}") # Optional logging

            # 4. Return SRT Response
            logger.info("Sending SRT response...")
            original_base_name = Path(file.filename or "transcription").stem
            headers = {
                'Content-Disposition': f'attachment; filename="{original_base_name}.srt"'
            }
            # Ensure srt_content is not empty before returning
            if not srt_content:
                 logger.warning("Transcription resulted in empty content.")
                 # Decide return value: empty string or error? Let's return empty.
                 # raise HTTPException(status_code=500, detail="Transcription failed to produce content.")

            return PlainTextResponse(content=srt_content, media_type='text/plain', headers=headers)
        
        except Exception as e:
            # Ensure any exception before returning/raising is logged
            # including potential HTTPExceptions raised intentionally
            if isinstance(e, HTTPException):
                logger.error(f"HTTPException caught: Status={e.status_code}, Detail={e.detail}")
                raise e # Re-raise HTTPException
            else:
                logger.exception("Unhandled error during transcription process:") # Log full exception info
                raise HTTPException(status_code=500, detail="An unexpected error occurred.")

# Allow running with uvicorn directly (e.g., `python -m uvicorn backend.main:app --reload`)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5175) # Use different port than Node server 
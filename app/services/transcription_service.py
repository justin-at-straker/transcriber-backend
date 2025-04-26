import os
import logging
import asyncio
import io
import math
import time
from datetime import timedelta
from typing import List, Tuple, Any
import openai
import srt
from pydub import AudioSegment
from openai import OpenAI

from ..config import settings

logger = logging.getLogger(__name__)

# --- Constants ---
BYTES_PER_MB = 1024 * 1024

# --- Custom Exceptions ---
class TranscriptionError(Exception):
    """Base exception for transcription service errors."""
    pass

class OpenAIError(TranscriptionError):
    """Specific exception for OpenAI API errors."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code

class ChunkingError(TranscriptionError):
    """Specific exception for errors during audio chunking."""
    pass

# --- Helper: Transcribe Single Chunk ---
async def _transcribe_chunk_openai(client: OpenAI, audio_chunk_data: bytes, chunk_index: int) -> str:
    """Transcribes a single audio chunk using OpenAI directly from memory and returns SRT content."""
    logger.info(f"Processing chunk {chunk_index} directly from memory.")
    if not audio_chunk_data:
        logger.warning(f"Received empty audio data for chunk {chunk_index}, skipping transcription.")
        return f"ERROR: Empty audio data for chunk {chunk_index}"

    try:
        audio_file_like = io.BytesIO(audio_chunk_data)
        file_tuple = (f"chunk_{chunk_index}.wav", audio_file_like)
        logger.info(f"Transcribing chunk {chunk_index} with OpenAI (model: {settings.WHISPER_MODEL}, from memory)...")
        transcription_response = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model=settings.WHISPER_MODEL,
            file=file_tuple,
            response_format="srt",
        )
        srt_content = transcription_response
        logger.info(f"Chunk {chunk_index} transcribed successfully.")
        return srt_content
    except openai.APIError as e:
        logger.error(f"OpenAI API Error for chunk {chunk_index}: Status={e.status_code}, Message={e.message}")
        return f"ERROR: OpenAI API Error - {e.message}" # Propagate error message
    except Exception as e:
        logger.error(f"Unexpected error processing chunk {chunk_index}: {e}", exc_info=True)
        return f"ERROR: Unexpected error in chunk {chunk_index}"

# --- Helper: Simple Transcription (No Chunking) ---
async def _perform_simple_transcription(client: OpenAI, audio_path: str) -> str:
    """Performs transcription for files smaller than the API limit."""
    logger.info("Performing standard transcription.")
    try:
        with open(audio_path, "rb") as audio_file_handle:
            transcription_response = await asyncio.to_thread(
                 client.audio.transcriptions.create,
                 model=settings.WHISPER_MODEL,
                 file=audio_file_handle,
                 response_format="srt",
             )
        logger.info("Standard transcription successful.")
        return transcription_response
    except openai.APIError as e:
        logger.error(f"OpenAI API Error (standard): Status={e.status_code}, Message={e.message}")
        raise OpenAIError(f"OpenAI API Error: {e.message}", status_code=e.status_code) from e
    except Exception as e:
        logger.error(f"Error during standard OpenAI call: {e}", exc_info=True)
        raise TranscriptionError(f"Standard transcription failed: {e}") from e


# --- Helper: Prepare Audio Chunks ---
def _prepare_audio_chunks(audio_path: str, file_size_bytes: int) -> Tuple[List[bytes], int]:
    """Loads audio, calculates chunk parameters, and returns list of chunk data bytes and duration."""
    try:
        logger.info(f"Loading audio file {audio_path} with pydub for chunking...")
        audio = AudioSegment.from_wav(audio_path)
        logger.info(f"Audio duration: {audio.duration_seconds:.2f} seconds")

        if audio.duration_seconds <= 0:
             raise ChunkingError("Audio file has zero or negative duration.")

        bytes_per_second = file_size_bytes / audio.duration_seconds
        target_chunk_size_bytes = settings.TARGET_CHUNK_SIZE_MB * BYTES_PER_MB
        # Ensure chunk duration is at least 1 second to avoid overly small chunks
        chunk_duration_ms = max(1000, int((target_chunk_size_bytes / bytes_per_second) * 1000))

        num_chunks = math.ceil(len(audio) / chunk_duration_ms)
        if num_chunks == 0:
             raise ChunkingError("Calculated zero chunks for the audio.")
        logger.info(f"Splitting audio into {num_chunks} chunks of approx {chunk_duration_ms / 1000:.2f}s each (Target: {settings.TARGET_CHUNK_SIZE_MB}MB)." )

        chunks_data = []
        chunk_start_ms = 0
        for i in range(num_chunks):
            chunk_end_ms = min(chunk_start_ms + chunk_duration_ms, len(audio))
            if chunk_start_ms >= chunk_end_ms:
                logger.warning(f"Skipping potentially empty chunk {i} (start={chunk_start_ms}, end={chunk_end_ms})")
                continue # Avoid creating zero-length chunks

            audio_chunk_segment = audio[chunk_start_ms:chunk_end_ms]

            buffer = io.BytesIO()
            audio_chunk_segment.export(buffer, format="wav")
            buffer.seek(0)
            chunk_data = buffer.read()
            chunks_data.append(chunk_data)

            chunk_start_ms = chunk_end_ms
            if chunk_start_ms >= len(audio):
                 break # Stop if we've processed the whole audio length

        if not chunks_data:
             raise ChunkingError("No valid audio chunk data could be generated.")

        return chunks_data, chunk_duration_ms

    except (OSError, ValueError, TypeError) as e:
        logger.error(f"Error loading/processing audio with pydub: {e}", exc_info=True)
        raise ChunkingError(f"Audio processing error: {e}") from e


# --- Helper: Combine SRT Results ---
def _combine_srt_results(chunk_results: List[str], chunk_duration_ms: int) -> str:
    """Combines SRT results from chunks, adjusting timestamps."""
    all_subs = []
    last_chunk_end_time = timedelta(seconds=0)
    processed_chunk_count = 0
    total_chunks = len(chunk_results)

    for i, chunk_result in enumerate(chunk_results):
        estimated_chunk_duration = timedelta(milliseconds=chunk_duration_ms)

        if isinstance(chunk_result, str) and chunk_result.startswith("ERROR:"):
            logger.error(f"Skipping failed or oversized chunk {i}: {chunk_result}")
            # Advance time offset by the estimated duration for subsequent valid chunks
            last_chunk_end_time += estimated_chunk_duration
            continue

        # Process valid SRT content
        processed_chunk_count += 1
        logger.info(f"Processing SRT for chunk {i}")
        try:
            chunk_subs = list(srt.parse(chunk_result))
            if not chunk_subs:
                logger.warning(f"Chunk {i} produced empty SRT content.")
                last_chunk_end_time += estimated_chunk_duration # Still advance time
                continue

            # Adjust timestamps relative to the end of the previous valid chunk
            current_chunk_offset = last_chunk_end_time
            for sub in chunk_subs:
                sub.start += current_chunk_offset
                sub.end += current_chunk_offset
                all_subs.append(sub)

            # Update end time based on the actual last subtitle of this chunk
            last_chunk_end_time = chunk_subs[-1].end

        except Exception as parse_err:
            logger.error(f"Failed to parse or process SRT for chunk {i}: {parse_err}", exc_info=True)
            # Failed parsing a valid chunk, advance time offset by estimate
            last_chunk_end_time += estimated_chunk_duration

    if not all_subs:
        logger.warning(f"Chunked transcription resulted in no valid subtitles after processing {processed_chunk_count}/{total_chunks} chunks.")
        return "" # Return empty string if no subtitles found

    logger.info(f"Combining {len(all_subs)} subtitles from {processed_chunk_count} successful chunks.")
    final_subs = srt.sort_and_reindex(all_subs)
    return srt.compose(final_subs)


# --- Helper: Chunked Transcription ---
async def _perform_chunked_transcription(client: OpenAI, audio_path: str, file_size_bytes: int) -> str:
    """Handles transcription for files exceeding the API limit by chunking."""
    logger.info("Performing chunked transcription.")
    openai_api_limit_mb = settings.OPENAI_API_LIMIT_MB

    try:
        # 1. Prepare Chunks
        chunks_data, chunk_duration_ms = _prepare_audio_chunks(audio_path, file_size_bytes)
        num_chunks = len(chunks_data)

        # 2. Create Transcription Tasks
        tasks = []
        for i, chunk_data in enumerate(chunks_data):
            chunk_mb = len(chunk_data) / BYTES_PER_MB
            if chunk_mb >= openai_api_limit_mb:
                 logger.warning(f"Chunk {i} size ({chunk_mb:.2f}MB) prepared exceeds API limit ({openai_api_limit_mb}MB), skipping. Adjust TARGET_CHUNK_SIZE_MB.")
                 # Use placeholder result for skipped/oversized chunks
                 tasks.append(asyncio.sleep(0, result=f"ERROR: Chunk {i} too large ({chunk_mb:.2f}MB)"))
            else:
                # Pass client, data, and index to the transcription helper
                tasks.append(_transcribe_chunk_openai(client, chunk_data, i))

        if not tasks:
            raise ChunkingError("No transcription tasks could be created from chunks.")

        # 3. Execute Tasks Concurrently
        logger.info(f"Created {len(tasks)} transcription tasks. Running concurrently...")
        results = await asyncio.gather(*tasks)
        logger.info("All transcription tasks finished.")

        # 4. Combine Results
        srt_content = _combine_srt_results(results, chunk_duration_ms)
        return srt_content

    except (ChunkingError, TranscriptionError) as e: # Propagate specific errors
         raise e
    except Exception as e:
        logger.error(f"Unexpected error during chunked transcription process: {e}", exc_info=True)
        raise TranscriptionError(f"Chunked transcription failed unexpectedly: {e}") from e


# --- Main Service Function ---
async def process_and_transcribe(converted_audio_path: str) -> str:
    """Processes the converted WAV file, transcribes it (using chunking if necessary), and returns SRT."""
    start_time = time.time()
    logger.info(f"Starting transcription process for {converted_audio_path}")

    try:
        file_size_bytes = os.path.getsize(converted_audio_path)
        file_size_mb = file_size_bytes / BYTES_PER_MB
        logger.info(f"Converted file size: {file_size_mb:.2f} MB")
    except OSError as e:
        logger.error(f"Could not get size of converted file {converted_audio_path}: {e}")
        raise TranscriptionError(f"Failed to access converted file: {e}") from e

    # Initialize OpenAI client once
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        raise OpenAIError(f"OpenAI client initialization failed: {e}") from e

    openai_api_limit_mb = settings.OPENAI_API_LIMIT_MB
    srt_content = ""

    try:
        # Decide transcription strategy
        if file_size_mb < openai_api_limit_mb:
            logger.info(f"File size ({file_size_mb:.2f}MB) is within limit ({openai_api_limit_mb}MB).")
            srt_content = await _perform_simple_transcription(client, converted_audio_path)
        else:
            logger.info(f"File size ({file_size_mb:.2f}MB) exceeds limit ({openai_api_limit_mb}MB).")
            srt_content = await _perform_chunked_transcription(client, converted_audio_path, file_size_bytes)

        # Final check for empty content (could be valid for silent audio)
        if not srt_content:
             logger.warning("Transcription resulted in empty content.")

    # Catch exceptions from helpers or client init
    except (OpenAIError, ChunkingError, TranscriptionError) as e:
        logger.error(f"Transcription failed: {e}")
        raise e # Re-raise specific errors for the route to handle
    except Exception as e:
        logger.error(f"An unexpected error occurred during transcription: {e}", exc_info=True)
        raise TranscriptionError(f"Unexpected transcription error: {e}") from e

    end_time = time.time()
    logger.info(f"Transcription process completed in {end_time - start_time:.2f}s.")
    return srt_content 
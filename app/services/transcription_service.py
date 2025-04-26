import os
import logging
import asyncio
import io
import math
import time
from datetime import timedelta
import openai
import srt
from pydub import AudioSegment
from openai import OpenAI

# Assuming file_utils is in the same parent directory structure
from ..utils.file_utils import cleanup_temp_file

logger = logging.getLogger(__name__)

# --- Constants ---
OPENAI_API_LIMIT_MB = 24 # Use slightly less than 25MB limit
BYTES_PER_MB = 1024 * 1024
TARGET_CHUNK_SIZE_MB = 20 # Target size for each chunk

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

# --- Helper Function for Transcribing a Single Chunk ---
async def _transcribe_chunk_openai(client: OpenAI, audio_chunk_data: bytes, chunk_index: int, temp_dir: str) -> str:
    """Transcribes a single audio chunk using OpenAI directly from memory and returns SRT content."""
    logger.info(f"Processing chunk {chunk_index} directly from memory.")

    # Check if data is empty
    if not audio_chunk_data:
        logger.warning(f"Received empty audio data for chunk {chunk_index}, skipping transcription.")
        return f"ERROR: Empty audio data for chunk {chunk_index}"

    try:
        # Wrap in-memory bytes data in BytesIO
        audio_file_like = io.BytesIO(audio_chunk_data)
        # Provide a filename tuple (name, file-like object)
        file_tuple = (f"chunk_{chunk_index}.wav", audio_file_like)

        # Transcribe using OpenAI
        logger.info(f"Transcribing chunk {chunk_index} with OpenAI (from memory)...")
        # Run the blocking OpenAI API call in a separate thread
        transcription_response = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1",
            file=file_tuple, # Pass the tuple here
            response_format="srt",
        )
        # The response for format 'srt' is directly the SRT string
        srt_content = transcription_response
        logger.info(f"Chunk {chunk_index} transcribed successfully.")
        return srt_content

    except openai.APIError as e:
        logger.error(f"OpenAI API Error for chunk {chunk_index}: Status={e.status_code}, Message={e.message}")
        return f"ERROR: OpenAI API Error - {e.message}"
    except Exception as e:
        logger.error(f"Unexpected error processing chunk {chunk_index}: {e}", exc_info=True)
        return f"ERROR: Unexpected error in chunk {chunk_index}"
    # No finally block needed as we are not creating temp files here

# --- Main Service Function ---
async def process_and_transcribe(converted_audio_path: str, api_key: str, temp_dir: str) -> str:
    """Processes the converted WAV file, transcribes it (using chunking if necessary), and returns SRT."""
    
    try:
        file_size_bytes = os.path.getsize(converted_audio_path)
        file_size_mb = file_size_bytes / BYTES_PER_MB
        logger.info(f"Converted file size: {file_size_mb:.2f} MB")
    except OSError as e:
        logger.error(f"Could not get size of converted file {converted_audio_path}: {e}")
        raise TranscriptionError(f"Failed to access converted file: {e}") from e

    client = OpenAI(api_key=api_key)
    srt_content = ""
    openai_start_time = time.time()

    # --- Decide Transcription Strategy ---
    if file_size_mb < OPENAI_API_LIMIT_MB:
        # --- Simple Transcription (File size within limit) ---
        logger.info(f"File size ({file_size_mb:.2f}MB) is within limit. Using standard transcription.")
        try:
            with open(converted_audio_path, "rb") as audio_file_handle:
                transcription_response = await asyncio.to_thread(
                     client.audio.transcriptions.create,
                     model="whisper-1",
                     file=audio_file_handle,
                     response_format="srt",
                 )
            srt_content = transcription_response
            logger.info("Standard transcription successful.")
        except openai.APIError as e:
            logger.error(f"OpenAI API Error (standard): Status={e.status_code}, Message={e.message}")
            raise OpenAIError(f"OpenAI API Error: {e.message}", status_code=e.status_code) from e
        except Exception as e:
            logger.error(f"Error during standard OpenAI call: {e}", exc_info=True)
            raise TranscriptionError(f"Standard transcription failed: {e}") from e

    else:
        # --- Chunked Transcription (File size exceeds limit) ---
        logger.info(f"File size ({file_size_mb:.2f}MB) exceeds limit ({OPENAI_API_LIMIT_MB}MB). Starting chunked transcription.")

        try:
            logger.info(f"Loading audio file {converted_audio_path} with pydub...")
            audio = AudioSegment.from_wav(converted_audio_path)
            logger.info(f"Audio duration: {audio.duration_seconds:.2f} seconds")

            if audio.duration_seconds <= 0:
                 raise ChunkingError("Audio file has zero or negative duration.")

            # Calculate chunk duration based on target size (approximate)
            bytes_per_second = file_size_bytes / audio.duration_seconds
            target_chunk_size_bytes = TARGET_CHUNK_SIZE_MB * BYTES_PER_MB
            # Ensure chunk duration is at least 1 second
            chunk_duration_ms = max(1000, int((target_chunk_size_bytes / bytes_per_second) * 1000))

            num_chunks = math.ceil(len(audio) / chunk_duration_ms)
            if num_chunks == 0:
                 raise ChunkingError("Calculated zero chunks for the audio.")
            logger.info(f"Splitting audio into {num_chunks} chunks of approx {chunk_duration_ms / 1000:.2f}s each.")

            tasks = []
            chunk_start_ms = 0
            for i in range(num_chunks):
                chunk_end_ms = min(chunk_start_ms + chunk_duration_ms, len(audio))
                if chunk_start_ms >= chunk_end_ms:
                    logger.warning(f"Skipping empty chunk {i} (start={chunk_start_ms}, end={chunk_end_ms})")
                    continue # Avoid creating zero-length chunks
                
                audio_chunk = audio[chunk_start_ms:chunk_end_ms]

                # Export chunk to bytes in memory
                buffer = io.BytesIO()
                audio_chunk.export(buffer, format="wav")
                buffer.seek(0)
                chunk_data = buffer.read()

                # Check chunk size before creating task
                chunk_mb = len(chunk_data) / BYTES_PER_MB
                if chunk_mb >= OPENAI_API_LIMIT_MB:
                     # This might happen if the bitrate estimation was off or audio segment has high silence density?
                     logger.warning(f"Chunk {i} size ({chunk_mb:.2f}MB) exceeds limit ({OPENAI_API_LIMIT_MB}MB), skipping transcription task. Adjust TARGET_CHUNK_SIZE_MB if this happens often.")
                     # We'll create a placeholder result to maintain order and estimate time offset later
                     tasks.append(asyncio.sleep(0, result=f"ERROR: Chunk {i} too large")) # Placeholder task
                else:
                    tasks.append(_transcribe_chunk_openai(client, chunk_data, i, temp_dir))

                chunk_start_ms = chunk_end_ms
                if chunk_start_ms >= len(audio):
                     break # Stop if we've processed the whole audio length

            if not tasks:
                raise ChunkingError("No valid audio chunks could be generated for transcription.")

            logger.info(f"Created {len(tasks)} transcription tasks. Running concurrently...")
            results = await asyncio.gather(*tasks) # Gather results including potential error strings
            logger.info("All transcription tasks finished.")

            # --- Combine SRT Results ---
            all_subs = []
            last_chunk_end_time = timedelta(seconds=0) # Track the end time of the last *valid* subtitle from the previous chunk
            processed_chunk_count = 0

            for i, chunk_result in enumerate(results):
                 # Estimate the expected duration of this chunk (for offset calculation if chunk failed)
                 # Use the planned duration, assuming chunks are roughly equal
                 current_chunk_start_ms = i * chunk_duration_ms
                 estimated_chunk_duration = timedelta(milliseconds=chunk_duration_ms)
                 # More accurate: calculate expected end based on next chunk's start
                 # expected_end_ms = min((i + 1) * chunk_duration_ms, len(audio))
                 # estimated_chunk_duration = timedelta(milliseconds=expected_end_ms - current_chunk_start_ms)

                 if isinstance(chunk_result, str) and chunk_result.startswith("ERROR:"):
                     logger.error(f"Skipping failed or oversized chunk {i}: {chunk_result}")
                     # Add the *estimated* duration of the failed chunk to the offset for subsequent chunks
                     # Advance based on the last known good time + estimated duration
                     last_chunk_end_time += estimated_chunk_duration
                     continue # Skip processing this chunk's SRT

                 # If we are here, chunk_result should be valid SRT content
                 processed_chunk_count += 1
                 logger.info(f"Processing SRT for chunk {i}")
                 try:
                     chunk_subs = list(srt.parse(chunk_result))
                     if not chunk_subs:
                         logger.warning(f"Chunk {i} produced empty SRT content.")
                         # Still advance the offset by the estimated duration
                         last_chunk_end_time += estimated_chunk_duration
                         continue

                     # Adjust timestamps: Add the end time of the *previous* chunk's last subtitle
                     current_chunk_offset = last_chunk_end_time
                     for sub in chunk_subs:
                         sub.start += current_chunk_offset
                         sub.end += current_chunk_offset
                         all_subs.append(sub)

                     # IMPORTANT: Update last_chunk_end_time using the end time of the last subtitle in *this* chunk
                     last_chunk_end_time = chunk_subs[-1].end

                 except Exception as parse_err:
                     logger.error(f"Failed to parse or process SRT for chunk {i}: {parse_err}", exc_info=True)
                     # Failed parsing a supposedly successful chunk. Advance time offset by estimate.
                     last_chunk_end_time += estimated_chunk_duration

            if not all_subs:
                logger.warning(f"Chunked transcription resulted in no valid subtitles after processing {processed_chunk_count}/{len(tasks)} chunks.")
                # Return empty SRT or raise error? Let's return empty for now.
                srt_content = ""
            else:
                logger.info(f"Combining {len(all_subs)} subtitles from {processed_chunk_count} successful chunks.")
                # Re-index subtitles sequentially
                final_subs = srt.sort_and_reindex(all_subs)
                srt_content = srt.compose(final_subs)

        except (OSError, ValueError, TypeError) as e: # Catch pydub/audio loading errors
             logger.error(f"Error loading/processing audio with pydub: {e}", exc_info=True)
             raise ChunkingError(f"Audio processing error: {e}") from e
        except TranscriptionError as e: # Propagate specific errors
             raise e
        except Exception as e:
            logger.error(f"Unexpected error during chunked transcription process: {e}", exc_info=True)
            raise TranscriptionError(f"Chunked transcription failed unexpectedly: {e}") from e

    openai_end_time = time.time()
    logger.info(f"OpenAI transcription process completed in {openai_end_time - openai_start_time:.2f}s.")

    # Final check for empty content
    if not srt_content:
         logger.warning("Transcription resulted in empty content.")
         # Return empty string rather than raising an error, could be valid (e.g., silent audio)

    return srt_content 
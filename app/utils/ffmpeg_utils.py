import ffmpeg
import logging
import os
import time

# Import settings
from ..config import settings

logger = logging.getLogger(__name__)

class FfmpegError(Exception):
    """Custom exception for FFmpeg errors."""
    def __init__(self, message, stderr=None):
        super().__init__(message)
        self.stderr = stderr

def convert_to_wav(input_path: str, output_path: str):
    """Converts an input audio/video file to 16kHz mono WAV using FFmpeg."""
    logger.info(f"Starting FFmpeg conversion: {input_path} -> {output_path}")
    start_time = time.time()

    # Determine ffmpeg command path
    ffmpeg_cmd = settings.FFMPEG_CMD or 'ffmpeg'
    logger.info(f"Using FFmpeg command: {ffmpeg_cmd}")

    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path, ar=16000, ac=1, sample_fmt='s16', vn=None) # ar=16k, ac=1, sample_fmt=s16, no video
            # Use quiet=False to see ffmpeg logs if needed
            .run(cmd=[ffmpeg_cmd, '-nostdin'], capture_stdout=True, capture_stderr=True, quiet=True)
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode('utf8', errors='ignore') if e.stderr else 'N/A'
        logger.error(f"FFmpeg Error during conversion: {e} - Stderr: {stderr}")
        raise FfmpegError("FFmpeg conversion failed.", stderr=stderr) from e
    except FileNotFoundError:
        logger.error(f"FFmpeg command '{ffmpeg_cmd}' not found. Check installation or FFMPEG_CMD setting.")
        raise FfmpegError(f"FFmpeg command '{ffmpeg_cmd}' not found.")
    except Exception as e:
        logger.error(f"Unexpected error during FFmpeg conversion: {e}", exc_info=True)
        raise FfmpegError(f"Unexpected FFmpeg error: {e}") from e

    end_time = time.time()
    logger.info(f"FFmpeg conversion finished successfully in {end_time - start_time:.2f}s.")

    if not os.path.exists(output_path):
        logger.error("FFmpeg conversion reported success, but output file not found.")
        raise FfmpegError("FFmpeg conversion finished but output file not found.")

    return output_path 
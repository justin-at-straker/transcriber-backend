import os
import logging

logger = logging.getLogger(__name__)

async def cleanup_temp_file(file_path: str):
    """Removes a temporary file, logging errors."""
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.info(f"Successfully deleted temp file: {file_path}")
    except OSError as e:
        logger.error(f"Failed to delete temp file {file_path}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error deleting temp file {file_path}: {e}", exc_info=True) 
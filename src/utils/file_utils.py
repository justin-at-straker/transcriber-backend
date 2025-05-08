import os
import logging
import httpx
import requests
from ..config import settings

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

async def upload_to_file_server(file_path: str, original_file_name: str, content_type: str, task_uuid: str, client_id: str) -> str:
    """
    Uploads a file to the file server (GridFS) asynchronously.

    Args:
        file_path: Path to the local file to upload.
        original_file_name: The name the file should have (used in file_tuple).
        content_type: The MIME type of the file.
        task_uuid: The task UUID for tracking/logging.
        client_id: The client ID for context/logging (not sent in GridFS PUT body).

    Returns:
        The file_id of the uploaded file.

    Raises:
        Exception if the upload fails.
    """
    upload_url = f"{settings.FILE_SERVICE_API}/gridfs"
    logger.info(f"Task {task_uuid} (Client {client_id}): Uploading {original_file_name} (from {file_path}, type {content_type}) to {upload_url}")

    try:
        with open(file_path, "rb") as f:
            # For httpx, the files parameter is typically a dict where values are tuples:
            # (filename, file_object, content_type)
            files_param = {'file': (original_file_name, f, content_type)}
            
            async with httpx.AsyncClient() as client:
                response = await client.put(upload_url, files=files_param)

            response.raise_for_status()
            response_data = response.json()
            logger.info(f"Task {task_uuid}: Successfully uploaded {original_file_name} to GridFS. Response: {response_data}")
            file_id = response_data.get("id")
            if not file_id:
                raise Exception("File ID not found in GridFS response after upload.")
            return file_id
    except httpx.HTTPStatusError as e:
        error_message = f"HTTP error uploading to GridFS: {e.response.status_code} - {e.response.text}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e
    except httpx.RequestError as e:
        error_message = f"Request error uploading to GridFS: {e}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e
    except Exception as e:
        error_message = f"Unexpected error uploading {original_file_name} to GridFS: {e}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e

async def download_from_file_server(file_id: str, destination_path: str, task_uuid: str) -> None:
    """
    Downloads a file from the file server using its file_id.

    Args:
        file_id: The ID of the file on the server.
        destination_path: The local path to save the downloaded file.
        task_uuid: The task UUID for tracking/logging.
        token: Optional authentication token for the download.

    Raises:
        Exception if the download fails.
    """
    download_url = f"{settings.FILE_SERVICE_API}/files/{file_id}"
    logger.info(f"Task {task_uuid}: Downloading file_id {file_id} from {download_url} to {destination_path}")

    try:
        async with httpx.AsyncClient() as client_session:
            async with client_session.stream("GET", download_url, timeout=300) as response:
                response.raise_for_status()
                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
            logger.info(f"Task {task_uuid}: Successfully downloaded file_id {file_id} to {destination_path}")
    except httpx.HTTPStatusError as e:
        error_message = f"HTTP error downloading file_id {file_id}: {e.response.status_code} - {e.response.text}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e
    except httpx.RequestError as e:
        error_message = f"Request error downloading file_id {file_id}: {e}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e
    except Exception as e:
        error_message = f"Unexpected error downloading file_id {file_id}: {e}"
        logger.error(f"Task {task_uuid}: {error_message}", exc_info=True)
        raise Exception(error_message) from e

async def download_file_from_url(
    url: str,
    destination_path: str,
    auth_token: str | None = None,
    timeout: int = 300,
    task_uuid: str | None = None
) -> None:
    """
    Downloads a file from a given URL.

    Args:
        url: The URL to download the file from.
        destination_path: The local path to save the downloaded file.
        auth_token: Optional authentication token (Bearer token) for the request.
        timeout: Optional timeout in seconds for the request.
        task_uuid: Optional task UUID for more specific logging.

    Raises:
        Exception if the download fails.
    """
    log_prefix = f"Task {task_uuid}: " if task_uuid else ""
    logger.info(f"{log_prefix}Downloading file from {url} to {destination_path}")

    request_headers = {}
    if auth_token:
        request_headers["Authorization"] = f"Bearer {auth_token}"

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=request_headers, timeout=timeout) as response:
                response.raise_for_status()
                with open(destination_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
        logger.info(f"{log_prefix}Successfully downloaded file from {url} to {destination_path}")
    except httpx.HTTPStatusError as e:
        error_message = f"HTTP error {e.response.status_code} downloading from {url}: {e.response.text}"
        logger.error(f"{log_prefix}{error_message}", exc_info=True)
        raise Exception(error_message) from e
    except httpx.RequestError as e:
        error_message = f"Request error downloading from {url}: {e}"
        logger.error(f"{log_prefix}{error_message}", exc_info=True)
        raise Exception(error_message) from e
    except Exception as e:
        error_message = f"Unexpected error downloading from {url}: {e}"
        logger.error(f"{log_prefix}{error_message}", exc_info=True)
        raise Exception(error_message) from e 
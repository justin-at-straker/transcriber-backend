import logging
import os
import tempfile
import asyncio
from buglog import notify_exception

from src.models.stream_event import TranscriptionTaskData
from src.models.stream_event import StreamData
from src.services.transcription_service import process_and_transcribe, TranscriptionError, OpenAIError, ChunkingError
from src.utils.ffmpeg_utils import convert_to_wav, FfmpegError
from src.redis.stream import publish_stream_event
from src.utils.file_utils import upload_to_file_server, download_file_from_url
from src.utils.task import set_task_running, set_task_success, set_task_failed

logger = logging.getLogger(__name__)


class TaskHandler:
    def __init__(self, stream: str, task: TranscriptionTaskData):
        self.stream = stream
        self.task = task

    async def process(self):
        logger.info(f"Processing task: {self.task.task_uuid} for file: {self.task.file_name}")
        logger.debug(f"Task data: {self.task}")

        set_task_running(self.task.task_uuid)

        error_message = None
        srt_content = None
        output_file_id = None
        output_file_name = None

        try:
            with tempfile.TemporaryDirectory(prefix="transcriber_") as temp_dir:
                logger.info(f"Task {self.task.task_uuid}: Created temporary directory: {temp_dir}")
                
                original_input_file_name = self.task.file_name or "downloaded_file"
                original_input_file_path = os.path.join(temp_dir, original_input_file_name)

                logger.info(f"Task {self.task.task_uuid}: Downloading from {self.task.download_url} to {original_input_file_path}")
                
                await download_file_from_url(
                    url=self.task.download_url,
                    destination_path=original_input_file_path,
                    auth_token=self.task.token,
                    timeout=300,
                    task_uuid=self.task.task_uuid
                )
                logger.info(f"Task {self.task.task_uuid}: Successfully downloaded input file {original_input_file_path} using utility function")

                base_filename = os.path.splitext(original_input_file_name)[0]
                converted_audio_path = os.path.join(temp_dir, f"{base_filename}_converted.wav")
                
                logger.info(f"Task {self.task.task_uuid}: Converting {original_input_file_path} to {converted_audio_path}")
                await asyncio.to_thread(convert_to_wav, original_input_file_path, converted_audio_path)
                logger.info(f"Task {self.task.task_uuid}: Successfully converted file to WAV: {converted_audio_path}")
                
                logger.info(f"Task {self.task.task_uuid}: Starting transcription for {converted_audio_path}")
                srt_content = await process_and_transcribe(converted_audio_path)
                logger.info(f"Task {self.task.task_uuid}: Transcription successful.")
                if not srt_content:
                    logger.warning(f"Task {self.task.task_uuid}: Transcription resulted in empty SRT content.")
                    notify_exception(Exception("Transcription resulted in empty SRT content."))
                    raise Exception("Transcription resulted in empty SRT content.")

                if srt_content:
                    srt_file_name = f"{base_filename}.srt"
                    srt_file_path = os.path.join(temp_dir, srt_file_name)
                    with open(srt_file_path, "w", encoding="utf-8") as sf:
                        sf.write(srt_content)
                    logger.info(f"Task {self.task.task_uuid}: Saved SRT content to temporary file {srt_file_path}")
                    
                    output_file_id = await upload_to_file_server(
                        file_path=srt_file_path,
                        original_file_name=srt_file_name,
                        content_type="text/plain",
                        task_uuid=self.task.task_uuid,
                        client_id=self.task.client_id
                    )
                    logger.info(f"Task {self.task.task_uuid}: SRT file uploaded. File ID: {output_file_id}")
                elif not error_message:
                    logger.info(f"Task {self.task.task_uuid}: No SRT content to upload.")
                    notify_exception(Exception("No SRT content to upload."))
                    raise Exception("No SRT content to upload.")
        except FfmpegError as e_ffmpeg:
            logger.error(f"Task {self.task.task_uuid}: FFmpeg conversion failed: {e_ffmpeg.stderr or e_ffmpeg}", exc_info=True)
            notify_exception(e_ffmpeg)
            error_message = f"FFmpeg conversion failed: {e_ffmpeg.stderr or e_ffmpeg}"
        except (OpenAIError, ChunkingError, TranscriptionError) as e_transcribe_service:
            logger.error(f"Task {self.task.task_uuid}: Transcription service error: {e_transcribe_service}", exc_info=True)
            notify_exception(e_transcribe_service)
            error_message = f"Transcription service error: {e_transcribe_service}"
        except Exception as e_process:
            logger.error(f"Task {self.task.task_uuid}: Error during file processing/transcription: {e_process}", exc_info=True)
            notify_exception(e_process)
            error_message = str(e_process)
            
        if output_file_id:
            output_file_name = f"{os.path.splitext(original_input_file_name)[0]}.srt"

        stream_payload_dict = StreamData(
            task_uuid=self.task.task_uuid,
            client_id=self.task.client_id,
            file_id=output_file_id,
            file_name=output_file_name,
            source_file_name=self.task.file_name,
            error=error_message if error_message else None,
            tokens=self.task.tokens,
            symlink=self.task.symlink 
        )

        target_stream_name = self.task.callback_uri

        if not target_stream_name:
            logger.warning(f"Task {self.task.task_uuid}: No result stream name (callback_uri) provided. Skipping publishing results.")
        else:
            logger.info(f"Task {self.task.task_uuid}: Preparing to publish results to stream '{target_stream_name}'. Payload: {stream_payload_dict}")
            try:
                entry_id = await asyncio.to_thread(publish_stream_event, target_stream_name, stream_payload_dict.model_dump())
                logger.info(f"Task {self.task.task_uuid}: Successfully published results to stream '{target_stream_name}'. Entry ID: {entry_id}")
            except Exception as e_publish:
                notify_exception(e_publish)
                logger.error(f"Task {self.task.task_uuid}: Failed to publish results to stream '{target_stream_name}': {e_publish}", exc_info=True)
                set_task_failed(self.task.task_uuid, e_publish)
                
        logger.info(f"Task {self.task.task_uuid}: Processing finished.")
        set_task_success(self.task.task_uuid, stream_payload_dict)

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from src.models.task import TaskLog, TaskStatus
from src.database import engines
from src.models.stream_event import StreamData
from typing import List
from slack_sdk.web.async_client import AsyncWebClient # type: ignore
from slack_sdk.errors import SlackApiError
import logging
import asyncio

from src.config import settings

logger = logging.getLogger(__name__)


async def monitor_stuck_tasks(check_interval_seconds: int = 600):
    """Periodically checks for tasks stuck in the RUNNING state and notifies Slack."""
    slack_client = None
    if settings.SLACK_BOT_TOKEN and settings.SLACK_CHANNEL_ID:
        slack_client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
        logger.info("Slack client initialized for stuck task notifications.")
    else:
        logger.warning("Slack token or channel ID not configured. Stuck task notifications will be disabled.")

    while True:
        try:
            logger.info("Checking for stuck tasks...")
            # Use the default timeout (1 hour) defined in check_running_tasks
            stuck_tasks = check_running_tasks()
            if stuck_tasks:
                logger.warning(f"Found {len(stuck_tasks)} potentially stuck tasks (running > 1 hour):")
                for task in stuck_tasks:
                    task_uuid = task.uuid
                    started_at = task.started_at
                    logger.warning(f"  - Task UUID: {task_uuid}, Started at: {started_at}")
                    
                    # Mark task as failed
                    try:
                        set_task_failed(task_uuid, Exception("Task is stuck in the RUNNING state for more than 1 hour"))
                    except Exception as fail_err:
                         logger.error(f"Failed to set task {task_uuid} to FAILED state: {fail_err}", exc_info=True)

                    # Send Slack notification
                    if slack_client:
                        message = (
                            f"🚨 *Stuck Transcription Task Detected* (`{settings.ENVIRONMENT.title()}`)\n"
                            f"*Task UUID:* `{task_uuid}`\n"
                            f"*Started At:* `{started_at}`\n"
                            f"Task has been running for over 1 hour and marked as FAILED."
                        )
                        try:
                            await slack_client.chat_postMessage(
                                channel=settings.SLACK_CHANNEL_ID,
                                text=message
                            )
                            logger.info(f"Slack notification sent for stuck task {task_uuid}")
                        except SlackApiError as e:
                            logger.error(f"Error sending Slack notification for task {task_uuid}: {e.response['error']}")
                        except Exception as slack_err:
                             logger.error(f"An unexpected error occurred sending Slack notification for task {task_uuid}: {slack_err}", exc_info=True)


            else:
                logger.info("No stuck tasks found.")
        except Exception as e:
            logger.error(f"Error during stuck task check: {e}", exc_info=True)
            # Optional: Add buglog notification here if desired
            # buglog.notify_exception(e, message="Error checking for stuck tasks")

        await asyncio.sleep(check_interval_seconds)

def check_running_tasks(timeout_seconds: int = 3600) -> List[TaskLog]:
    """
    Check for tasks that have been running for longer than timeout_seconds.

    Args:
        timeout_seconds (int): The maximum allowed running time in seconds. Defaults to 3600 (1 hour).

    Returns:
        List[TaskLog]: A list of TaskLog objects representing the overdue tasks.
    """
    with Session(engines["sitecommons"]) as session:
        timeout_delta = timedelta(seconds=timeout_seconds)
        cutoff_time = datetime.now(timezone.utc) - timeout_delta

        stmt = select(TaskLog).where(
            TaskLog.task_status == TaskStatus.RUNNING.value,
            TaskLog.started_at < cutoff_time
        )
        result = session.execute(stmt)
        return list(result.scalars().all())

def set_task_running(task_uuid: str) -> None:
    # Set the task's status to `Running`.
    with Session(engines["sitecommons"]) as session:
        stmt = (
            update(TaskLog)
            .where(TaskLog.uuid == task_uuid)
            .values(
                {
                    "task_status": TaskStatus.RUNNING.value,
                    "started_at": datetime.now(timezone.utc),
                }
            )
        )
        session.execute(stmt)
        session.commit()

def set_task_success(task_uuid: str, result: StreamData) -> None:
    # Set the task's status to `Success` and store the task's result.
    with Session(engines["sitecommons"]) as session:
        stmt = (
            update(TaskLog)
            .where(TaskLog.uuid == task_uuid)
            .values(
                {
                    "task_status": TaskStatus.SUCCESS.value,
                    "task_result": result.model_dump(),
                    "finished_at": datetime.now(timezone.utc),
                }
            )
        )
        session.execute(stmt)
        session.commit()

def set_task_failed(task_uuid: str, exception: Exception | None = None) -> None:
    # Set the task's status to `Failed` and store the exception.
    with Session(engines["sitecommons"]) as session:
        stmt = (
            update(TaskLog)
            .where(TaskLog.uuid == task_uuid)
            .values(
                {
                    "task_status": TaskStatus.FAILED.value,
                    "task_result": {"exception": str(exception)},
                    "finished_at": datetime.now(timezone.utc),
                }
            )
        )
        session.execute(stmt)
        session.commit()

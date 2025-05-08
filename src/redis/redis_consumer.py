import json
import httpx
from buglog import notify_exception
from straker_redis_streams.consumer import ConsumerClient  # type: ignore


from src.tasks.task_handler import TaskHandler
from src.models.stream_event import TranscriptionTaskData

class TranscriptionConsumer(ConsumerClient):
    timeout = httpx.Timeout(10.0)

    async def process_stream(
        self,
        stream: str,
        message_id: str,
        event_data: dict[str, str],
    ) -> bool | None:
        await self.redis.xack(
            stream,
            self.consumer_group,
            message_id,
        )
        data = json.loads(event_data["data"])
        assert isinstance(data, dict)

        handler = TaskHandler(
            stream=stream,
            task=TranscriptionTaskData(**data)
        )
        await handler.process()
        return True

    async def on_process_stream_error(
        self,
        exception: Exception,
        stream: str,
        message_id: str,
        event_data: dict[str, str],
    ) -> None:
        buglog_extra = {
            "stream": stream,
            "consumer_group": self.consumer_group,
            "consumer": self.consumer,
            "message_id": message_id,
            "event": event_data,
        }
        if isinstance(exception, httpx.HTTPError):
            buglog_extra["request"] = {
                "url": str(exception.request.url),
                "body": exception.request.content.decode(),
            }
        if isinstance(exception, httpx.HTTPStatusError):
            buglog_extra["response"] = {
                "url": str(exception.request.url),
                "status_code": exception.response.status_code,
                "response_body": exception.response.content.decode(),
            }

        notify_exception(exception, extra=buglog_extra)

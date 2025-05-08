from requests import post

def publish_stream_event(stream: str, data: dict) -> None:
    """
    Publishes a task event to the stream.

    stream:
        The stream to publish the event to.
    data:
        The data to publish.
    """
    response = post(
       stream,
        headers={
            "Content-Type": "application/json",
            "charset": "utf-8",
        },
        json={
            "data": data,
            "source": "transcription_worker"
        }
    )
    response.raise_for_status()

    # Return the entry ID.
    return response.json()["entry_id"]

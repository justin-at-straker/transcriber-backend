from enum import Enum
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy import JSON
from typing import List, Dict, Union

class Base(DeclarativeBase):
    pass

class TaskStatus(Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"

class TaskLog(Base):
    __tablename__ = "transcriber_task_consumer_queue"

    uuid: Mapped[str] = mapped_column(name="obj_uuid", primary_key=True)
    entry_id: Mapped[str] = mapped_column()
    stream: Mapped[str] = mapped_column(name="event_name")
    task_status: Mapped[str] = mapped_column()
    task_data: Mapped[Dict] = mapped_column(JSON)
    task_result: Mapped[Union[List, Dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime] = mapped_column()
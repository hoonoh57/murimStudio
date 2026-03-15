from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Optional


class UploadStatus(str, Enum):
    PENDING = 'pending'
    UPLOADING = 'uploading'
    DONE = 'done'
    ERROR = 'error'


class ScriptStatus(str, Enum):
    GENERATED = 'generated'
    REVIEW = 'review'
    APPROVED = 'approved'
    PUBLISHED = 'published'
    ERROR = 'error'


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Channel:
    id: Optional[int] = None
    code: str = ''
    name: str = ''
    youtube_channel_id: str = ''
    timezone: str = 'UTC'
    peak_hour: int = 18
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Project:
    id: Optional[int] = None
    title: str = ''
    episodes: str = ''
    language: str = 'en'
    status: str = 'pending'
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class Script:
    id: Optional[int] = None
    project_id: Optional[int] = None
    language: str = 'en'
    content: str = ''
    status: ScriptStatus = ScriptStatus.GENERATED
    cost_usd: float = 0.0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class MediaItem:
    id: Optional[int] = None
    project_id: Optional[int] = None
    type: str = 'image'
    path: str = ''
    prompt: str = ''
    status: UploadStatus = UploadStatus.PENDING
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

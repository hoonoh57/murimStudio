from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import List, Optional

class UploadStatus(str, Enum):
    PENDING = 'pending'
    UPLOADING = 'uploading'
    DONE = 'done'

class ScriptStatus(str, Enum):
    GENERATED = 'generated'
    REVIEW = 'review'
    APPROVED = 'approved'
    PUBLISHED = 'published'

@dataclass
class Channel:
    id: Optional[int] = None
    code: str = ''  # en, ko, id, th
    name: str = ''
    youtube_channel_id: str = ''
    timezone: str = ''
    peak_hour: int = 18
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Project:
    id: Optional[int] = None
    title: str = ''
    episodes: str = ''
    language: str = 'en'
    status: str = 'pending'
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class Script:
    id: Optional[int] = None
    project_id: Optional[int] = None
    language: str = 'en'
    content: str = ''
    status: ScriptStatus = ScriptStatus.GENERATED
    cost_usd: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class MediaItem:
    id: Optional[int] = None
    project_id: Optional[int] = None
    type: str = 'image'  # image, voice, video
    path: str = ''
    status: UploadStatus = UploadStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


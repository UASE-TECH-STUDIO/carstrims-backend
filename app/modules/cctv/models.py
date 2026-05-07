from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class StreamType(str, Enum):
    RTSP = "rtsp"
    HLS = "hls"
    IP = "ip"
    NVR = "nvr"
    CLOUD = "cloud"


class CCTVStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class CCTVBase(BaseModel):
    dealerId: str
    cameraName: str
    cameraLocation: str
    streamUrl: str
    streamType: StreamType = StreamType.RTSP
    provider: Optional[str] = None


class CCTVCreate(CCTVBase):
    pass


class CCTVStreamInDB(CCTVBase):
    id: Optional[str] = Field(None, alias="_id")
    cameraId: str
    status: CCTVStatus = CCTVStatus.OFFLINE
    lastOnline: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class CCTVResponse(CCTVBase):
    id: str
    cameraId: str
    status: CCTVStatus
    lastOnline: Optional[datetime] = None
    createdAt: datetime

    class Config:
        populate_by_name = True

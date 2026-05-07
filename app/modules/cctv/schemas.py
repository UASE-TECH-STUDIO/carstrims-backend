from pydantic import BaseModel
from typing import Optional


class CameraCreateRequest(BaseModel):
    cameraName: str
    cameraLocation: str
    streamUrl: str
    streamType: Optional[str] = "rtsp"
    provider: Optional[str] = None


class CameraUpdateRequest(BaseModel):
    cameraName: Optional[str] = None
    cameraLocation: Optional[str] = None
    streamUrl: Optional[str] = None
    streamType: Optional[str] = None
    provider: Optional[str] = None

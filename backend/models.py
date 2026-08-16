"""FastAPI 请求模型。"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CookieTestRequest(BaseModel):
    cookie: str = Field(..., min_length=1, max_length=16384, description="浏览器 Cookie 字符串")
    save: bool = True


class ParseRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)


class TaskCreateRequest(BaseModel):
    url: Optional[str] = None
    urls: Optional[list[str]] = None
    batch_text: Optional[str] = None
    page_indexes: Optional[list[int]] = None
    quality: Optional[int] = Field(None, ge=1, le=200)
    codec: Optional[str] = "auto"
    output_format: Optional[str] = None
    download_subtitles: Optional[bool] = None
    download_danmaku: Optional[bool] = None
    download_thumbnail: Optional[bool] = None


class SettingsUpdateRequest(BaseModel):
    download_dir: Optional[str] = None
    filename_template: Optional[str] = None
    default_quality: Optional[Any] = None
    preferred_codec: Optional[str] = None
    output_format: Optional[str] = None
    max_concurrent: Optional[int] = None
    proxy: Optional[str] = None
    download_subtitles: Optional[bool] = None
    download_danmaku: Optional[bool] = None
    download_thumbnail: Optional[bool] = None
    auto_parse_on_paste: Optional[bool] = None
    auto_open_folder: Optional[bool] = None

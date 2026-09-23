"""Proveedor de YouTube. El flujo de descarga vive en ``ytdlp_backend``."""
from __future__ import annotations

import re

from app.core.base import DownloadType, register_downloader
from app.core.ytdlp_backend import YtDlpDownloader

_YOUTUBE_URL = re.compile(
    r"^(https?://)?((www|m|music)\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/\S+",
    re.IGNORECASE,
)


@register_downloader
class YouTubeDownloader(YtDlpDownloader):
    name = "YouTube"
    supported_types = (DownloadType.MP3, DownloadType.M4A, DownloadType.MP4)

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return bool(_YOUTUBE_URL.match(url.strip()))

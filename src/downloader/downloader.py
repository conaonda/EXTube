"""유튜브 영상 다운로드 기능."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

YOUTUBE_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?"
    r"(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)"
    r"[A-Za-z0-9_-]{11}$"
)


@dataclass
class DownloadResult:
    """다운로드 결과."""

    video_path: Path
    title: str
    video_id: str
    resolution: str


def validate_youtube_url(url: str) -> bool:
    """유튜브 URL 유효성을 검사한다."""
    return bool(YOUTUBE_URL_PATTERN.match(url))


@dataclass
class VideoMetadata:
    """영상 메타데이터."""

    duration: float | None  # 초 (라이브 스트림 등은 None)
    title: str
    video_id: str
    height: int | None
    filesize_approx: int | None  # 바이트 (추정)


def fetch_video_metadata(url: str) -> VideoMetadata:
    """yt-dlp로 영상 메타데이터를 사전 조회한다 (다운로드 없이).

    Raises:
        ValueError: 유효하지 않은 URL
        RuntimeError: 메타데이터 조회 실패
    """
    if not validate_youtube_url(url):
        raise ValueError(f"유효하지 않은 유튜브 URL: {url}")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(f"메타데이터 조회 실패: {e}") from e

    return VideoMetadata(
        duration=info.get("duration"),
        title=info.get("title", ""),
        video_id=info["id"],
        height=info.get("height"),
        filesize_approx=info.get("filesize_approx") or info.get("filesize"),
    )


def download_video(
    url: str,
    output_dir: Path,
    max_height: int = 1080,
) -> DownloadResult:
    """유튜브 영상을 다운로드한다.

    Args:
        url: 유튜브 URL
        output_dir: 출력 디렉토리
        max_height: 최대 해상도 높이 (기본 1080p)

    Returns:
        DownloadResult 다운로드 결과

    Raises:
        ValueError: 유효하지 않은 URL
        RuntimeError: 다운로드 실패
    """
    if not validate_youtube_url(url):
        raise ValueError(f"유효하지 않은 유튜브 URL: {url}")

    output_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": (
            f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"
        ),
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(f"다운로드 실패: {e}") from e

    video_id = info["id"]
    ext = info.get("ext", "mp4")
    video_path = output_dir / f"{video_id}.{ext}"
    resolution = f"{info.get('height', 'unknown')}p"

    return DownloadResult(
        video_path=video_path,
        title=info.get("title", ""),
        video_id=video_id,
        resolution=resolution,
    )

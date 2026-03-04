"""downloader 모듈 단위 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from src.downloader.downloader import (
    DownloadResult,
    download_video,
    validate_youtube_url,
)


class TestValidateYoutubeUrl:
    """URL 유효성 검사 테스트."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "http://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ],
    )
    def test_valid_urls(self, url: str):
        assert validate_youtube_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "not-a-url",
            "https://vimeo.com/123456",
            "https://youtube.com/watch?v=short",
            "https://youtube.com/playlist?list=abc",
        ],
    )
    def test_invalid_urls(self, url: str):
        assert validate_youtube_url(url) is False


class TestDownloadVideo:
    """영상 다운로드 테스트."""

    def test_invalid_url_raises(self, tmp_path):
        with pytest.raises(ValueError, match="유효하지 않은"):
            download_video("bad-url", tmp_path)

    @patch("src.downloader.downloader.yt_dlp.YoutubeDL")
    def test_successful_download(self, mock_ydl_class, tmp_path):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {
            "id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "ext": "mp4",
            "height": 1080,
        }

        # 가짜 파일 생성
        (tmp_path / "dQw4w9WgXcQ.mp4").touch()

        result = download_video(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            tmp_path,
        )

        assert isinstance(result, DownloadResult)
        assert result.video_id == "dQw4w9WgXcQ"
        assert result.title == "Test Video"
        assert result.resolution == "1080p"

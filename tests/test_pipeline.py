"""파이프라인 오케스트레이터 테스트."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.pipeline import Pipeline, PipelineResult


class TestPipeline:
    """Pipeline 클래스 테스트."""

    def test_invalid_url_raises_error(self, tmp_path):
        """유효하지 않은 URL에서 ValueError를 발생시킨다."""
        pipeline = Pipeline(output_dir=tmp_path / "out")
        with pytest.raises(ValueError, match="유효하지 않은 유튜브 URL"):
            pipeline.run("not-a-url")

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_full_pipeline(
        self, mock_download, mock_extract, mock_reconstruct, tmp_path
    ):
        """전체 파이프라인이 순서대로 실행된다."""
        output_dir = tmp_path / "out"

        # 다운로드 mock
        video_path = tmp_path / "video.mp4"
        video_path.touch()
        mock_download.return_value = MagicMock(
            video_path=video_path,
            title="Test Video",
            video_id="abc123",
            resolution="1080p",
        )

        # 추출 mock
        mock_extract.return_value = MagicMock(
            output_dir=output_dir / "extraction",
            total_extracted=10,
            total_filtered=2,
            frames=[],
        )

        # 복원 mock
        mock_reconstruct.return_value = MagicMock(
            workspace_dir=output_dir / "reconstruction",
            sparse_dir=output_dir / "reconstruction" / "sparse",
            num_images=8,
            num_registered=7,
            num_points3d=500,
            camera_model="SIMPLE_RADIAL",
            steps_completed=["feature_extraction", "exhaustive_matching"],
        )

        pipeline = Pipeline(output_dir=output_dir)
        result = pipeline.run("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert isinstance(result, PipelineResult)
        assert result.video_title == "Test Video"
        assert result.extraction.total_extracted == 10
        assert result.reconstruction.num_points3d == 500

        mock_download.assert_called_once()
        mock_extract.assert_called_once()
        mock_reconstruct.assert_called_once()

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_pipeline_custom_options(
        self, mock_download, mock_extract, mock_reconstruct, tmp_path
    ):
        """커스텀 옵션이 각 단계에 전달된다."""
        output_dir = tmp_path / "out"
        video_path = tmp_path / "video.mp4"
        video_path.touch()

        mock_download.return_value = MagicMock(video_path=video_path)
        mock_extract.return_value = MagicMock(
            total_extracted=5, total_filtered=0, frames=[]
        )
        mock_reconstruct.return_value = MagicMock(
            num_images=5, num_registered=5, num_points3d=100
        )

        pipeline = Pipeline(
            output_dir=output_dir,
            max_height=720,
            frame_interval=2.0,
            blur_threshold=50.0,
            camera_model="PINHOLE",
            export_ply=False,
        )
        pipeline.run("https://youtu.be/dQw4w9WgXcQ")

        mock_download.assert_called_once_with(
            "https://youtu.be/dQw4w9WgXcQ",
            output_dir / "download",
            max_height=720,
        )
        mock_extract.assert_called_once_with(
            video_path,
            output_dir / "extraction",
            interval=2.0,
            blur_threshold=50.0,
        )
        mock_reconstruct.assert_called_once_with(
            output_dir / "extraction" / "frames",
            output_dir / "reconstruction",
            camera_model="PINHOLE",
            export_ply=False,
        )

    @patch("src.pipeline.download_video")
    def test_pipeline_download_failure(self, mock_download, tmp_path):
        """다운로드 실패 시 RuntimeError를 전파한다."""
        mock_download.side_effect = RuntimeError("다운로드 실패")

        pipeline = Pipeline(output_dir=tmp_path / "out")
        with pytest.raises(RuntimeError, match="다운로드 실패"):
            pipeline.run("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


class TestCLI:
    """CLI 진입점 테스트."""

    def test_parse_args_defaults(self):
        """기본 인자가 올바르게 설정된다."""
        from src.__main__ import parse_args

        args = parse_args(["https://youtu.be/abc12345678"])
        assert args.url == "https://youtu.be/abc12345678"
        assert args.output_dir == Path("output")
        assert args.max_height == 1080
        assert args.frame_interval == 1.0
        assert args.blur_threshold == 100.0
        assert args.no_ply is False
        assert args.verbose is False

    def test_parse_args_custom(self):
        """커스텀 인자가 올바르게 파싱된다."""
        from src.__main__ import parse_args

        args = parse_args(
            [
                "https://youtu.be/abc12345678",
                "-o",
                "/tmp/out",
                "--max-height",
                "720",
                "--frame-interval",
                "2.0",
                "--blur-threshold",
                "50.0",
                "--camera-model",
                "PINHOLE",
                "--no-ply",
                "-v",
            ]
        )
        assert args.output_dir == Path("/tmp/out")
        assert args.max_height == 720
        assert args.frame_interval == 2.0
        assert args.blur_threshold == 50.0
        assert args.camera_model == "PINHOLE"
        assert args.no_ply is True
        assert args.verbose is True

    @patch("src.__main__.Pipeline")
    def test_main_success(self, mock_pipeline_cls, tmp_path):
        """성공 시 0을 반환한다."""
        from src.__main__ import main

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = MagicMock(
            output_dir=tmp_path,
            video_title="Test",
            extraction=MagicMock(total_extracted=10),
            reconstruction=MagicMock(
                num_points3d=100,
                workspace_dir=tmp_path,
            ),
        )
        mock_pipeline_cls.return_value = mock_pipeline

        result = main(
            [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "-o",
                str(tmp_path),
            ]
        )
        assert result == 0

    @patch("src.__main__.Pipeline")
    def test_main_invalid_url(self, mock_pipeline_cls):
        """잘못된 URL 시 1을 반환한다."""
        from src.__main__ import main

        mock_pipeline = MagicMock()
        mock_pipeline.run.side_effect = ValueError("유효하지 않은 유튜브 URL")
        mock_pipeline_cls.return_value = mock_pipeline

        result = main(["bad-url"])
        assert result == 1

    @patch("src.__main__.Pipeline")
    def test_main_runtime_error(self, mock_pipeline_cls):
        """런타임 에러 시 1을 반환한다."""
        from src.__main__ import main

        mock_pipeline = MagicMock()
        mock_pipeline.run.side_effect = RuntimeError("COLMAP 실패")
        mock_pipeline_cls.return_value = mock_pipeline

        result = main(["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
        assert result == 1

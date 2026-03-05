"""extractor 모듈 단위 테스트."""

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from src.extractor.extractor import (
    ExtractionResult,
    extract_and_filter,
    extract_frames,
    filter_blurry_frames,
)


@pytest.fixture()
def sample_frames(tmp_path: Path) -> list[Path]:
    """테스트용 가짜 프레임 파일 생성."""
    frames = []
    for i in range(5):
        p = tmp_path / f"frame_{i:06d}.jpg"
        # 다양한 크기로 생성하여 blur_score 차이를 만듦
        p.write_bytes(b"\xff" * (1000 * (i + 1)))
        frames.append(p)
    return frames


class TestExtractFrames:
    """프레임 추출 테스트."""

    def test_missing_video_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            extract_frames(tmp_path / "nonexistent.mp4", tmp_path / "out")

    @patch("src.extractor.extractor.subprocess.run")
    def test_successful_extraction(self, mock_run, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        # ffmpeg 성공 시뮬레이션
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        # 가짜 프레임 파일 생성
        for i in range(3):
            (out_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 500)

        result = extract_frames(video, out_dir, interval=1.0)
        assert len(result) == 3
        mock_run.assert_called_once()

    @patch("src.extractor.extractor.subprocess.run")
    def test_ffmpeg_failure_raises(self, mock_run, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()

        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "error"

        with pytest.raises(RuntimeError, match="ffmpeg"):
            extract_frames(video, tmp_path / "out")


class TestFilterBlurryFrames:
    """블러 필터링 테스트."""

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.compute_blur_score")
    def test_filter_by_score(self, mock_blur, sample_frames: list[Path]):
        mock_blur.side_effect = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        passed, filtered, scores = filter_blurry_frames(
            sample_frames, blur_threshold=2500.0
        )
        assert len(passed) == 3
        assert len(filtered) == 2
        assert len(scores) == 5

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.compute_blur_score")
    def test_all_pass(self, mock_blur, sample_frames: list[Path]):
        mock_blur.return_value = 500.0
        passed, filtered, scores = filter_blurry_frames(
            sample_frames, blur_threshold=0.0
        )
        assert len(passed) == 5
        assert len(filtered) == 0


class TestExtractAndFilter:
    """통합 추출+필터링 테스트."""

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.extract_frames")
    @patch("src.extractor.extractor.compute_blur_score")
    def test_extract_and_filter(self, mock_blur, mock_extract, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        out_dir = tmp_path / "output"
        frames_dir = out_dir / "frames"
        frames_dir.mkdir(parents=True)

        # 가짜 프레임
        frame_paths = []
        for i in range(4):
            p = frames_dir / f"frame_{i:06d}.jpg"
            p.write_bytes(b"\xff" * 100)
            frame_paths.append(p)

        mock_extract.return_value = frame_paths
        # 첫 2개는 블러, 나머지는 선명 (이제 1회만 호출)
        mock_blur.side_effect = [50.0, 30.0, 200.0, 300.0]

        result = extract_and_filter(video, out_dir, blur_threshold=100.0)

        assert isinstance(result, ExtractionResult)
        assert result.total_extracted == 4
        assert result.total_filtered == 2

        # 메타데이터 파일 확인
        metadata_path = out_dir / "metadata.json"
        assert metadata_path.exists()
        metadata = json.loads(metadata_path.read_text())
        assert len(metadata) == 4


class TestParallelBlurScore:
    """병렬 블러 점수 계산 테스트."""

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.compute_blur_score")
    def test_parallel_blur_scoring(self, mock_blur, sample_frames: list[Path]):
        """병렬 처리 결과가 순차 처리와 동일한지 검증."""
        mock_blur.side_effect = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        passed, filtered, scores = filter_blurry_frames(
            sample_frames, blur_threshold=2500.0
        )
        assert len(passed) == 3
        assert len(filtered) == 2
        assert len(scores) == 5
        # 순서 유지 확인
        assert passed[0].name == "frame_000002.jpg"
        assert passed[1].name == "frame_000003.jpg"
        assert passed[2].name == "frame_000004.jpg"

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.compute_blur_score")
    def test_progress_callback_called(self, mock_blur, sample_frames: list[Path]):
        """progress_callback이 올바른 인자로 호출되는지 검증."""
        mock_blur.return_value = 500.0
        callback = MagicMock()

        filter_blurry_frames(sample_frames, blur_threshold=100.0, progress_callback=callback)

        assert callback.call_count == 5
        # 모든 호출에서 total은 5
        for call_args in callback.call_args_list:
            completed, total = call_args[0]
            assert total == 5
            assert 1 <= completed <= 5

    @patch("src.extractor.extractor.concurrent.futures.ProcessPoolExecutor", ThreadPoolExecutor)
    @patch("src.extractor.extractor.compute_blur_score")
    def test_single_frame_no_error(self, mock_blur, tmp_path: Path):
        """단일 프레임에서도 병렬 처리가 정상 동작하는지 검증."""
        single_frame = tmp_path / "frame_000000.jpg"
        single_frame.write_bytes(b"\xff" * 100)
        mock_blur.return_value = 300.0

        passed, filtered, scores = filter_blurry_frames(
            [single_frame], blur_threshold=100.0
        )
        assert len(passed) == 1
        assert len(filtered) == 0
        assert scores[single_frame.name] == 300.0

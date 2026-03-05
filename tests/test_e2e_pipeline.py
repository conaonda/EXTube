"""핵심 파이프라인 E2E 통합 테스트.

유튜브 URL → 영상 다운로드 → 프레임 추출 → SfM 복원 전체 흐름을 검증한다.
GPU 없이 CI에서 실행 가능한 mock 모드를 지원한다.

pytest -m e2e 로 실행.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from src.downloader.downloader import DownloadResult
from src.extractor.extractor import ExtractionResult, FrameMetadata
from src.pipeline import Pipeline, PipelineResult
from src.reconstruction.reconstruction import ReconstructionResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
SAMPLE_VIDEO_ID = "dQw4w9WgXcQ"


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """E2E 테스트용 임시 작업 디렉토리."""
    return tmp_path / "e2e_workspace"


@pytest.fixture()
def sample_video(tmp_path: Path) -> Path:
    """가짜 영상 파일 fixture."""
    video = tmp_path / "download" / f"{SAMPLE_VIDEO_ID}.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"\x00" * 1024)
    return video


@pytest.fixture()
def sample_frames(tmp_path: Path) -> list[Path]:
    """가짜 프레임 이미지 fixture (5장)."""
    frames_dir = tmp_path / "extraction" / "frames"
    frames_dir.mkdir(parents=True)
    frames = []
    for i in range(1, 6):
        frame = frames_dir / f"frame_{i:06d}.jpg"
        frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * (100 + i * 10))
        frames.append(frame)
    return frames


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_download_mock(video_path: Path):
    """download_video mock: 실제 파일을 생성하고 DownloadResult를 반환."""

    def _mock_download(url, output_dir, *, max_height=1080):
        output_dir.mkdir(parents=True, exist_ok=True)
        dest = output_dir / f"{SAMPLE_VIDEO_ID}.mp4"
        dest.write_bytes(b"\x00" * 1024)
        return DownloadResult(
            video_path=dest,
            title="E2E Test Video",
            video_id=SAMPLE_VIDEO_ID,
            resolution=f"{max_height}p",
        )

    return _mock_download


def _make_extract_mock():
    """extract_and_filter mock: 프레임 파일과 metadata.json을 생성."""

    def _mock_extract(video_path, output_dir, *, interval=1.0, blur_threshold=100.0):
        frames_dir = output_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        filtered_dir = output_dir / "filtered"
        filtered_dir.mkdir(parents=True, exist_ok=True)

        num_frames = 5
        num_filtered = 1
        metadata_list = []
        for i in range(num_frames):
            fname = f"frame_{i + 1:06d}.jpg"
            is_filtered = i == num_frames - 1
            score = 50.0 if is_filtered else 200.0

            if is_filtered:
                (filtered_dir / fname).write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)
            else:
                (frames_dir / fname).write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

            metadata_list.append(
                FrameMetadata(
                    frame_index=i,
                    timestamp=i * interval,
                    file_path=fname,
                    blur_score=score,
                    is_filtered=is_filtered,
                )
            )

        metadata_path = output_dir / "metadata.json"
        from dataclasses import asdict

        metadata_path.write_text(
            json.dumps(
                [asdict(m) for m in metadata_list],
                ensure_ascii=False,
                indent=2,
            )
        )

        return ExtractionResult(
            output_dir=output_dir,
            total_extracted=num_frames,
            total_filtered=num_filtered,
            frames=metadata_list,
        )

    return _mock_extract


def _make_reconstruct_mock():
    """reconstruct mock: COLMAP 아티팩트(DB, sparse model, PLY)를 생성."""

    def _mock_reconstruct(
        image_dir,
        workspace_dir,
        camera_model="SIMPLE_RADIAL",
        export_ply=True,
        timeout=3600,
        dense=False,
        max_image_size=0,
        gaussian_splatting=False,
        gs_max_iterations=None,
    ):
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # database.db
        db_path = workspace_dir / "database.db"
        db_path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        # sparse model
        sparse_dir = workspace_dir / "sparse"
        model_dir = sparse_dir / "0"
        model_dir.mkdir(parents=True)
        (model_dir / "cameras.bin").write_bytes(b"\x00" * 32)
        (model_dir / "images.bin").write_bytes(b"\x00" * 64)
        (model_dir / "points3D.bin").write_bytes(b"\x00" * 128)

        num_images = len(list(image_dir.glob("*.jpg")))
        num_registered = max(num_images - 1, 1)
        num_points3d = num_registered * 50

        steps = ["feature_extraction", "exhaustive_matching", "sparse_reconstruction"]

        # PLY export
        if export_ply:
            ply_path = workspace_dir / "points.ply"
            ply_header = (
                f"ply\nformat binary_little_endian 1.0\n"
                f"element vertex {num_points3d}\n"
                f"property float x\nproperty float y\nproperty float z\n"
                f"end_header\n"
            )
            ply_path.write_bytes(ply_header.encode() + b"\x00" * num_points3d * 12)
            steps.append("ply_export")

        # Dense reconstruction
        dense_dir = None
        num_dense_points = None
        if dense:
            dense_dir = workspace_dir / "dense"
            dense_dir.mkdir(parents=True)
            dense_ply = workspace_dir / "dense_points.ply"
            num_dense_points = num_points3d * 10
            dense_header = (
                f"ply\nformat binary_little_endian 1.0\n"
                f"element vertex {num_dense_points}\n"
                f"property float x\nproperty float y\nproperty float z\n"
                f"end_header\n"
            )
            dense_ply.write_bytes(dense_header.encode() + b"\x00" * 12)
            steps.extend(["image_undistortion", "patch_match_stereo", "stereo_fusion"])

        # 3DGS
        gs_ply_path = None
        gs_splat_path = None
        gs_num_iterations = None
        if gaussian_splatting:
            gs_dir = workspace_dir / "gaussian_splatting"
            gs_dir.mkdir(parents=True)
            gs_ply_path = gs_dir / "point_cloud.ply"
            gs_ply_path.write_bytes(b"ply\nend_header\n")
            gs_splat_path = gs_dir / "splat.splat"
            gs_splat_path.write_bytes(b"\x00" * 64)
            gs_num_iterations = gs_max_iterations or 7000
            steps.append("gaussian_splatting")

        # metadata
        metadata = {
            "num_images": num_images,
            "num_registered": num_registered,
            "num_points3d": num_points3d,
            "camera_model": camera_model,
            "steps_completed": steps,
        }
        (workspace_dir / "reconstruction_metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False)
        )

        return ReconstructionResult(
            workspace_dir=workspace_dir,
            sparse_dir=sparse_dir,
            num_images=num_images,
            num_registered=num_registered,
            num_points3d=num_points3d,
            camera_model=camera_model,
            steps_completed=steps,
            dense_dir=dense_dir,
            num_dense_points=num_dense_points,
            gs_ply_path=gs_ply_path,
            gs_splat_path=gs_splat_path,
            gs_num_iterations=gs_num_iterations,
        )

    return _mock_reconstruct


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestE2EPipelineMock:
    """mock 모드 E2E 테스트: 외부 도구 없이 전체 파이프라인 흐름을 검증한다."""

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_full_pipeline_sparse(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """sparse 모드 전체 파이프라인이 올바른 아티팩트를 생성한다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        pipeline = Pipeline(output_dir=workspace)
        result = pipeline.run(SAMPLE_URL)

        # 결과 타입 검증
        assert isinstance(result, PipelineResult)
        assert result.video_title == "E2E Test Video"

        # 다운로드 아티팩트
        download_dir = workspace / "download"
        assert download_dir.is_dir()
        video_files = list(download_dir.glob("*.mp4"))
        assert len(video_files) == 1

        # 프레임 추출 아티팩트
        extraction_dir = workspace / "extraction"
        assert extraction_dir.is_dir()
        frames_dir = extraction_dir / "frames"
        assert frames_dir.is_dir()
        frames = list(frames_dir.glob("frame_*.jpg"))
        assert len(frames) == 4  # 5 total - 1 filtered
        filtered_dir = extraction_dir / "filtered"
        assert filtered_dir.is_dir()
        filtered = list(filtered_dir.glob("frame_*.jpg"))
        assert len(filtered) == 1
        metadata_path = extraction_dir / "metadata.json"
        assert metadata_path.is_file()
        metadata = json.loads(metadata_path.read_text())
        assert len(metadata) == 5

        # 복원 아티팩트
        recon_dir = workspace / "reconstruction"
        assert recon_dir.is_dir()
        assert (recon_dir / "database.db").is_file()
        assert (recon_dir / "sparse" / "0" / "cameras.bin").is_file()
        assert (recon_dir / "sparse" / "0" / "images.bin").is_file()
        assert (recon_dir / "sparse" / "0" / "points3D.bin").is_file()
        assert (recon_dir / "points.ply").is_file()
        assert (recon_dir / "reconstruction_metadata.json").is_file()

        # 통계 검증
        assert result.extraction.total_extracted == 5
        assert result.extraction.total_filtered == 1
        assert result.reconstruction.num_registered > 0
        assert result.reconstruction.num_points3d > 0
        assert "feature_extraction" in result.reconstruction.steps_completed
        assert "exhaustive_matching" in result.reconstruction.steps_completed
        assert "sparse_reconstruction" in result.reconstruction.steps_completed
        assert "ply_export" in result.reconstruction.steps_completed

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_full_pipeline_with_dense(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """dense 모드가 추가 아티팩트를 생성한다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        pipeline = Pipeline(output_dir=workspace, dense=True)
        result = pipeline.run(SAMPLE_URL)

        recon_dir = workspace / "reconstruction"
        assert (recon_dir / "dense").is_dir()
        assert (recon_dir / "dense_points.ply").is_file()
        assert result.reconstruction.dense_dir is not None
        assert result.reconstruction.num_dense_points is not None
        assert result.reconstruction.num_dense_points > 0
        assert "stereo_fusion" in result.reconstruction.steps_completed

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_full_pipeline_with_gaussian_splatting(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """3DGS 모드가 splat/PLY 파일을 생성한다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        pipeline = Pipeline(
            output_dir=workspace,
            gaussian_splatting=True,
            gs_max_iterations=100,
        )
        result = pipeline.run(SAMPLE_URL)

        assert result.reconstruction.gs_ply_path is not None
        assert result.reconstruction.gs_ply_path.is_file()
        assert result.reconstruction.gs_splat_path is not None
        assert result.reconstruction.gs_splat_path.is_file()
        assert result.reconstruction.gs_num_iterations == 100
        assert "gaussian_splatting" in result.reconstruction.steps_completed

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_pipeline_call_order(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """파이프라인이 다운로드 → 추출 → 복원 순서로 호출된다."""
        call_order = []

        def track_download(*a, **kw):
            call_order.append("download")
            return _make_download_mock(workspace)(*a, **kw)

        def track_extract(*a, **kw):
            call_order.append("extract")
            return _make_extract_mock()(*a, **kw)

        def track_reconstruct(*a, **kw):
            call_order.append("reconstruct")
            return _make_reconstruct_mock()(*a, **kw)

        mock_download.side_effect = track_download
        mock_extract.side_effect = track_extract
        mock_reconstruct.side_effect = track_reconstruct

        Pipeline(output_dir=workspace).run(SAMPLE_URL)

        assert call_order == ["download", "extract", "reconstruct"]

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_pipeline_custom_options_propagate(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """커스텀 옵션이 각 단계에 올바르게 전달된다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        pipeline = Pipeline(
            output_dir=workspace,
            max_height=720,
            frame_interval=2.0,
            blur_threshold=50.0,
            camera_model="PINHOLE",
        )
        pipeline.run(SAMPLE_URL)

        # download_video 호출 인자 확인
        mock_download.assert_called_once()
        dl_kwargs = mock_download.call_args
        assert (
            dl_kwargs.kwargs.get("max_height") == 720
            or dl_kwargs[1].get("max_height") == 720
        )

        # extract_and_filter 호출 인자 확인
        mock_extract.assert_called_once()
        ext_kwargs = mock_extract.call_args
        assert ext_kwargs.kwargs.get("interval") == 2.0
        assert ext_kwargs.kwargs.get("blur_threshold") == 50.0

        # reconstruct 호출 인자 확인
        mock_reconstruct.assert_called_once()
        rec_kwargs = mock_reconstruct.call_args
        assert rec_kwargs.kwargs.get("camera_model") == "PINHOLE"

    def test_invalid_url_rejected(self, workspace):
        """유효하지 않은 URL이 즉시 거부된다."""
        pipeline = Pipeline(output_dir=workspace)
        with pytest.raises(ValueError, match="유효하지 않은 유튜브 URL"):
            pipeline.run("https://example.com/not-youtube")

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_extraction_metadata_integrity(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """추출 metadata.json이 올바른 구조를 가진다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        Pipeline(output_dir=workspace).run(SAMPLE_URL)

        metadata_path = workspace / "extraction" / "metadata.json"
        metadata = json.loads(metadata_path.read_text())

        for entry in metadata:
            assert "frame_index" in entry
            assert "timestamp" in entry
            assert "file_path" in entry
            assert "blur_score" in entry
            assert "is_filtered" in entry
            assert isinstance(entry["blur_score"], float)

        # 필터링된 프레임이 정확히 1개
        assert sum(1 for e in metadata if e["is_filtered"]) == 1

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_reconstruction_metadata_file(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """복원 메타데이터 파일이 올바르게 생성된다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        Pipeline(output_dir=workspace).run(SAMPLE_URL)

        meta_path = workspace / "reconstruction" / "reconstruction_metadata.json"
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text())
        assert "num_images" in meta
        assert "num_registered" in meta
        assert "num_points3d" in meta
        assert "steps_completed" in meta

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_ply_file_has_valid_header(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """생성된 PLY 파일이 유효한 헤더를 가진다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = _make_reconstruct_mock()

        Pipeline(output_dir=workspace).run(SAMPLE_URL)

        ply_path = workspace / "reconstruction" / "points.ply"
        assert ply_path.is_file()
        content = ply_path.read_bytes()
        assert content.startswith(b"ply\n")
        header_text = content.split(b"end_header")[0].decode()
        assert "element vertex" in header_text


@pytest.mark.e2e
class TestE2EPipelineErrorHandling:
    """파이프라인 에러 전파 E2E 테스트."""

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_download_failure_propagates(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """다운로드 실패가 올바르게 전파된다."""
        mock_download.side_effect = RuntimeError("네트워크 오류")

        with pytest.raises(RuntimeError, match="네트워크 오류"):
            Pipeline(output_dir=workspace).run(SAMPLE_URL)

        mock_extract.assert_not_called()
        mock_reconstruct.assert_not_called()

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_extraction_failure_propagates(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """프레임 추출 실패가 올바르게 전파된다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = RuntimeError("ffmpeg 실패")

        with pytest.raises(RuntimeError, match="ffmpeg 실패"):
            Pipeline(output_dir=workspace).run(SAMPLE_URL)

        mock_reconstruct.assert_not_called()

    @patch("src.pipeline.reconstruct")
    @patch("src.pipeline.extract_and_filter")
    @patch("src.pipeline.download_video")
    def test_reconstruction_failure_propagates(
        self, mock_download, mock_extract, mock_reconstruct, workspace
    ):
        """3D 복원 실패가 올바르게 전파된다."""
        mock_download.side_effect = _make_download_mock(workspace)
        mock_extract.side_effect = _make_extract_mock()
        mock_reconstruct.side_effect = RuntimeError("COLMAP 실패")

        with pytest.raises(RuntimeError, match="COLMAP 실패"):
            Pipeline(output_dir=workspace).run(SAMPLE_URL)

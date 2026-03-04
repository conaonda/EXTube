"""COLMAP 3D 복원 파이프라인 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from src.reconstruction.reconstruction import (
    ReconstructionResult,
    _run_colmap,
    exhaustive_matcher,
    feature_extractor,
    reconstruct,
    sparse_reconstructor,
)


class TestRunColmap:
    """_run_colmap 헬퍼 함수 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = _run_colmap("feature_extractor", ["--database_path", "db"])
        mock_run.assert_called_once()
        assert result.returncode == 0

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_failure_raises_runtime_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error message"
        )
        with pytest.raises(RuntimeError, match="COLMAP feature_extractor 실패"):
            _run_colmap("feature_extractor", ["--database_path", "db"])


class TestFeatureExtractor:
    """feature_extractor 함수 테스트."""

    def test_missing_image_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        db = tmp_path / "db.db"
        with pytest.raises(FileNotFoundError, match="이미지 디렉토리"):
            feature_extractor(missing, db)

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        db = tmp_path / "db.db"

        feature_extractor(image_dir, db, camera_model="PINHOLE")

        mock_colmap.assert_called_once_with(
            "feature_extractor",
            [
                "--database_path",
                str(db),
                "--image_path",
                str(image_dir),
                "--ImageReader.camera_model",
                "PINHOLE",
                "--ImageReader.single_camera",
                "1",
            ],
        )


class TestExhaustiveMatcher:
    """exhaustive_matcher 함수 테스트."""

    def test_missing_database(self, tmp_path):
        db = tmp_path / "nonexistent.db"
        with pytest.raises(FileNotFoundError, match="데이터베이스"):
            exhaustive_matcher(db)

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        db = tmp_path / "db.db"
        db.touch()

        exhaustive_matcher(db)

        mock_colmap.assert_called_once_with(
            "exhaustive_matcher",
            ["--database_path", str(db)],
        )


class TestSparseReconstructor:
    """sparse_reconstructor 함수 테스트."""

    def test_missing_database(self, tmp_path):
        db = tmp_path / "nonexistent.db"
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        output_dir = tmp_path / "sparse"
        with pytest.raises(FileNotFoundError, match="데이터베이스"):
            sparse_reconstructor(db, image_dir, output_dir)

    def test_missing_image_dir(self, tmp_path):
        db = tmp_path / "db.db"
        db.touch()
        image_dir = tmp_path / "nonexistent"
        output_dir = tmp_path / "sparse"
        with pytest.raises(FileNotFoundError, match="이미지 디렉토리"):
            sparse_reconstructor(db, image_dir, output_dir)

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        db = tmp_path / "db.db"
        db.touch()
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        output_dir = tmp_path / "sparse"

        sparse_reconstructor(db, image_dir, output_dir)

        assert output_dir.exists()
        mock_colmap.assert_called_once()


class TestReconstruct:
    """전체 파이프라인 reconstruct 함수 테스트."""

    def test_missing_image_dir(self, tmp_path):
        image_dir = tmp_path / "nonexistent"
        workspace = tmp_path / "workspace"
        with pytest.raises(FileNotFoundError, match="이미지 디렉토리"):
            reconstruct(image_dir, workspace)

    def test_too_few_images(self, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        (image_dir / "frame_000001.jpg").touch()
        workspace = tmp_path / "workspace"
        with pytest.raises(ValueError, match="최소 2장"):
            reconstruct(image_dir, workspace)

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_full_pipeline(self, mock_colmap, mock_subprocess, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(5):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"

        # COLMAP 명령 실행을 시뮬레이션
        def side_effect(command, args):
            if command == "feature_extractor":
                db = workspace / "database.db"
                db.parent.mkdir(parents=True, exist_ok=True)
                db.touch()
            elif command == "mapper":
                model_dir = workspace / "sparse" / "0"
                model_dir.mkdir(parents=True, exist_ok=True)
                (model_dir / "images.bin").write_bytes(b"\x00" * 1024)
                (model_dir / "points3D.bin").write_bytes(b"\x00" * 640)
                (model_dir / "cameras.bin").write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect

        # model_analyzer 출력 시뮬레이션
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 5\nPoints 3D = 120\n",
        )

        result = reconstruct(image_dir, workspace, export_ply=True)

        assert isinstance(result, ReconstructionResult)
        assert result.num_images == 5
        assert result.num_registered == 5
        assert result.num_points3d == 120
        assert result.workspace_dir == workspace
        assert "feature_extraction" in result.steps_completed
        assert "exhaustive_matching" in result.steps_completed
        assert "sparse_reconstruction" in result.steps_completed
        assert "ply_export" in result.steps_completed

        # 메타데이터 파일 확인
        metadata_path = workspace / "reconstruction_metadata.json"
        assert metadata_path.exists()

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_pipeline_without_ply_export(self, mock_colmap, mock_subprocess, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(3):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"

        def side_effect(command, args):
            if command == "feature_extractor":
                db = workspace / "database.db"
                db.parent.mkdir(parents=True, exist_ok=True)
                db.touch()
            elif command == "mapper":
                model_dir = workspace / "sparse" / "0"
                model_dir.mkdir(parents=True, exist_ok=True)
                (model_dir / "images.bin").write_bytes(b"\x00" * 512)
                (model_dir / "points3D.bin").write_bytes(b"\x00" * 128)
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect

        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 3\nPoints 3D = 50\n",
        )

        result = reconstruct(image_dir, workspace, export_ply=False)

        assert "ply_export" not in result.steps_completed
        assert len(result.steps_completed) == 3

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_colmap_failure_propagates(self, mock_colmap, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(3):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"

        mock_colmap.side_effect = RuntimeError("COLMAP feature_extractor 실패")

        with pytest.raises(RuntimeError, match="COLMAP"):
            reconstruct(image_dir, workspace)

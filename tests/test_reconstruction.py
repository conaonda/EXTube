"""COLMAP 3D 복원 파이프라인 테스트."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.reconstruction.reconstruction import (
    ReconstructionResult,
    _count_ply_points,
    _run_colmap,
    exhaustive_matcher,
    feature_extractor,
    image_undistorter,
    patch_match_stereo,
    potree_convert,
    reconstruct,
    sparse_reconstructor,
    stereo_fusion,
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
    def test_progress_callback_called(self, mock_colmap, mock_subprocess, tmp_path):
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
                (model_dir / "images.bin").write_bytes(b"\x00" * 1024)
                (model_dir / "points3D.bin").write_bytes(b"\x00" * 640)
                (model_dir / "cameras.bin").write_bytes(b"\x00" * 64)
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 3\nPoints 3D = 50\n",
        )

        calls = []
        reconstruct(
            image_dir,
            workspace,
            export_ply=True,
            progress_callback=lambda step, pct, msg: calls.append((step, pct, msg)),
        )

        # 5단계 진행률 콜백이 호출되었는지 확인
        stages_called = [c[0] for c in calls]
        assert "feature_matching" in stages_called
        assert "reconstruction" in stages_called
        assert "export" in stages_called
        # feature_matching 0%, 50%, 100% 호출 확인
        fm_calls = [
            (pct, msg) for step, pct, msg in calls if step == "feature_matching"
        ]
        assert fm_calls[0][0] == 0
        assert fm_calls[-1][0] == 100

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

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_dense_pipeline(self, mock_colmap, mock_subprocess, tmp_path):
        """Dense reconstruction (MVS) 파이프라인 테스트."""
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(5):
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
                (model_dir / "images.bin").write_bytes(b"\x00" * 1024)
                (model_dir / "points3D.bin").write_bytes(b"\x00" * 640)
                (model_dir / "cameras.bin").write_bytes(b"\x00" * 64)
            elif command == "image_undistorter":
                dense_dir = workspace / "dense"
                dense_dir.mkdir(parents=True, exist_ok=True)
            elif command == "stereo_fusion":
                # dense PLY 파일 생성 시뮬레이션
                output_path = None
                for j, arg in enumerate(args):
                    if arg == "--output_path" and j + 1 < len(args):
                        output_path = Path(args[j + 1])
                        break
                if output_path:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        "ply\nformat ascii 1.0\nelement vertex 50000\nend_header\n"
                    )
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect

        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 5\nPoints 3D = 120\n",
        )

        result = reconstruct(image_dir, workspace, dense=True)

        assert isinstance(result, ReconstructionResult)
        assert "image_undistortion" in result.steps_completed
        assert "patch_match_stereo" in result.steps_completed
        assert "stereo_fusion" in result.steps_completed
        assert result.dense_dir == workspace / "dense"
        assert result.num_dense_points == 50000

        # 메타데이터에 dense 정보 포함 확인
        import json

        metadata = json.loads((workspace / "reconstruction_metadata.json").read_text())
        assert metadata["num_dense_points"] == 50000

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_sparse_only_no_dense_fields(self, mock_colmap, mock_subprocess, tmp_path):
        """dense=False일 때 dense 관련 필드가 None인지 확인."""
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
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 3\nPoints 3D = 50\n",
        )

        result = reconstruct(image_dir, workspace, export_ply=False, dense=False)

        assert result.dense_dir is None
        assert result.num_dense_points is None
        assert "image_undistortion" not in result.steps_completed


class TestImageUndistorter:
    """image_undistorter 함수 테스트."""

    def test_missing_sparse_model(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError, match="Sparse 모델"):
            image_undistorter(tmp_path, missing, tmp_path / "output")

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        output_dir = tmp_path / "dense"

        image_undistorter(image_dir, sparse_dir, output_dir)

        mock_colmap.assert_called_once()
        call_args = mock_colmap.call_args
        assert call_args[0][0] == "image_undistorter"

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_max_image_size(self, mock_colmap, tmp_path):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        output_dir = tmp_path / "dense"

        image_undistorter(image_dir, sparse_dir, output_dir, max_image_size=2000)

        args = mock_colmap.call_args[0][1]
        assert "--max_image_size" in args
        assert "2000" in args


class TestPatchMatchStereo:
    """patch_match_stereo 함수 테스트."""

    def test_missing_workspace(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError, match="작업 디렉토리"):
            patch_match_stereo(missing)

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        ws = tmp_path / "dense"
        ws.mkdir()

        patch_match_stereo(ws)

        mock_colmap.assert_called_once()
        assert mock_colmap.call_args[0][0] == "patch_match_stereo"


class TestStereoFusion:
    """stereo_fusion 함수 테스트."""

    def test_missing_workspace(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError, match="작업 디렉토리"):
            stereo_fusion(missing, tmp_path / "out.ply")

    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_success(self, mock_colmap, tmp_path):
        ws = tmp_path / "dense"
        ws.mkdir()
        output = tmp_path / "output" / "dense.ply"

        stereo_fusion(ws, output)

        mock_colmap.assert_called_once()
        assert mock_colmap.call_args[0][0] == "stereo_fusion"
        assert output.parent.exists()


class TestCountPlyPoints:
    """_count_ply_points 함수 테스트."""

    def test_valid_ply(self, tmp_path):
        ply = tmp_path / "test.ply"
        ply.write_text("ply\nformat ascii 1.0\nelement vertex 12345\nend_header\n")
        assert _count_ply_points(ply) == 12345

    def test_missing_file(self, tmp_path):
        assert _count_ply_points(tmp_path / "missing.ply") == 0

    def test_no_vertex_element(self, tmp_path):
        ply = tmp_path / "test.ply"
        ply.write_text("ply\nformat ascii 1.0\nend_header\n")
        assert _count_ply_points(ply) == 0


class TestPotreeConvert:
    """potree_convert 함수 테스트."""

    @patch("src.reconstruction.reconstruction.shutil.which")
    def test_no_potree_converter(self, mock_which, tmp_path):
        """PotreeConverter가 없으면 None을 반환한다."""
        mock_which.return_value = None
        ply = tmp_path / "test.ply"
        ply.write_text("ply data")
        result = potree_convert(ply, tmp_path / "output")
        assert result is None

    def test_missing_ply_file(self, tmp_path):
        """PLY 파일이 없으면 FileNotFoundError."""
        with patch(
            "src.reconstruction.reconstruction.shutil.which",
            return_value="/usr/bin/PotreeConverter",
        ):
            with pytest.raises(FileNotFoundError):
                potree_convert(
                    tmp_path / "missing.ply",
                    tmp_path / "output",
                )

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_success(self, mock_run, tmp_path):
        """성공 시 metadata.json 경로를 반환한다."""
        with patch(
            "src.reconstruction.reconstruction.shutil.which",
            return_value="/usr/bin/PotreeConverter",
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr="",
            )
            ply = tmp_path / "test.ply"
            ply.write_text("ply data")
            output_dir = tmp_path / "output"
            output_dir.mkdir()
            meta = output_dir / "metadata.json"
            meta.write_text("{}")

            result = potree_convert(ply, output_dir)
            assert result == meta

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_failure(self, mock_run, tmp_path):
        """PotreeConverter 실패 시 RuntimeError."""
        with patch(
            "src.reconstruction.reconstruction.shutil.which",
            return_value="/usr/bin/PotreeConverter",
        ):
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="error",
            )
            ply = tmp_path / "test.ply"
            ply.write_text("ply data")

            with pytest.raises(RuntimeError, match="PotreeConverter"):
                potree_convert(ply, tmp_path / "output")


class TestRunColmapTimeout:
    """_run_colmap 타임아웃 처리 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_timeout_raises_user_friendly_error(self, mock_run):
        import subprocess as sp

        mock_run.side_effect = sp.TimeoutExpired(cmd="colmap", timeout=3600)
        with pytest.raises(RuntimeError, match="시간 초과"):
            _run_colmap("mapper", ["--arg", "val"])


class TestReconstructZeroPoints:
    """Sparse reconstruction 후 포인트 0개 실패 테스트."""

    @patch("src.reconstruction.reconstruction._parse_reconstruction_stats")
    @patch("src.reconstruction.reconstruction.sparse_reconstructor")
    @patch("src.reconstruction.reconstruction.exhaustive_matcher")
    @patch("src.reconstruction.reconstruction.feature_extractor")
    def test_zero_points3d_raises(
        self,
        mock_fe,
        mock_em,
        mock_sr,
        mock_stats,
        tmp_path,
    ):
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        (image_dir / "img1.jpg").write_bytes(b"fake")
        (image_dir / "img2.jpg").write_bytes(b"fake")
        workspace = tmp_path / "workspace"

        mock_stats.return_value = {
            "num_registered": 0,
            "num_points3d": 0,
        }

        with pytest.raises(RuntimeError, match="3D 포인트를 생성하지 못했습니다"):
            reconstruct(image_dir, workspace)

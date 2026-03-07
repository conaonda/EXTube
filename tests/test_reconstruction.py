"""COLMAP 3D 복원 파이프라인 테스트."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from src.reconstruction.reconstruction import (
    ColmapRetryConfig,
    ReconstructionResult,
    _cleanup_workspace,
    _count_ply_points,
    _load_checkpoint,
    _run_colmap,
    _save_checkpoint,
    exhaustive_matcher,
    feature_extractor,
    image_undistorter,
    is_colmap_retryable_error,
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
            retry_config=None,
            retry_callback=None,
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
            retry_config=None,
            retry_callback=None,
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
        def side_effect(command, args, **kwargs):
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

        def side_effect(command, args, **kwargs):
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

        def side_effect(command, args, **kwargs):
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

        def side_effect(command, args, **kwargs):
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
        import json as json_mod

        metadata = json_mod.loads(
            (workspace / "reconstruction_metadata.json").read_text()
        )
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

        def side_effect(command, args, **kwargs):
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


class TestIsColmapRetryableError:
    """is_colmap_retryable_error 판별 테스트."""

    def test_out_of_memory(self):
        assert is_colmap_retryable_error("CUDA out of memory") is True

    def test_gpu_error(self):
        assert is_colmap_retryable_error("GPU device error") is True

    def test_killed(self):
        assert is_colmap_retryable_error("Process killed by signal 9") is True

    def test_normal_error(self):
        assert is_colmap_retryable_error("Invalid camera model") is False

    def test_timeout(self):
        assert is_colmap_retryable_error("Connection timed out") is True


class TestRunColmapRetry:
    """_run_colmap 재시도 로직 테스트."""

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_retry_on_retryable_error(self, mock_run, mock_sleep):
        """재시도 가능한 오류 시 재시도 후 성공."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="CUDA out of memory"),
            MagicMock(returncode=0, stdout="ok", stderr=""),
        ]
        config = ColmapRetryConfig(
            max_retries=2,
            base_delay=1.0,
            backoff_multiplier=2.0,
        )
        result = _run_colmap("mapper", ["--arg", "val"], retry_config=config)
        assert result.returncode == 0
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(1.0)

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_no_retry_on_non_retryable_error(self, mock_run, mock_sleep):
        """재시도 불가능한 오류 시 즉시 실패."""
        mock_run.return_value = MagicMock(returncode=1, stderr="Invalid camera model")
        config = ColmapRetryConfig(max_retries=3)
        with pytest.raises(RuntimeError, match="Invalid camera model"):
            _run_colmap("mapper", ["--arg", "val"], retry_config=config)
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_max_retries_exhausted(self, mock_run, mock_sleep):
        """최대 재시도 횟수 초과 시 실패."""
        mock_run.return_value = MagicMock(returncode=1, stderr="CUDA out of memory")
        config = ColmapRetryConfig(
            max_retries=2,
            base_delay=1.0,
            backoff_multiplier=2.0,
        )
        with pytest.raises(RuntimeError, match="CUDA out of memory"):
            _run_colmap("mapper", ["--arg", "val"], retry_config=config)
        assert mock_run.call_count == 3  # 1 initial + 2 retries
        assert mock_sleep.call_count == 2

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_retry_callback_called(self, mock_run, mock_sleep):
        """재시도 시 callback이 호출되는지 확인."""
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="GPU device error"),
            MagicMock(returncode=0, stdout="ok", stderr=""),
        ]
        config = ColmapRetryConfig(max_retries=2, base_delay=1.0)
        callback = MagicMock()
        _run_colmap(
            "feature_extractor",
            ["--arg", "val"],
            retry_config=config,
            retry_callback=callback,
        )
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "feature_extractor"
        assert args[1] == 1  # attempt
        assert args[2] == 2  # max_retries

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_exponential_backoff(self, mock_run, mock_sleep):
        """지수 백오프 지연 확인."""
        mock_run.return_value = MagicMock(returncode=1, stderr="out of memory")
        config = ColmapRetryConfig(
            max_retries=3,
            base_delay=2.0,
            backoff_multiplier=3.0,
        )
        with pytest.raises(RuntimeError):
            _run_colmap("mapper", [], retry_config=config)
        # delays: 2.0, 6.0, 18.0
        assert mock_sleep.call_args_list == [
            call(2.0),
            call(6.0),
            call(18.0),
        ]


class TestRunColmapTracebackPreservation:
    """_run_colmap이 원본 traceback을 보존하는지 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_timeout_preserves_cause(self, mock_run):
        """TimeoutExpired의 원본 예외가 __cause__에 보존된다."""
        timeout_exc = subprocess.TimeoutExpired(cmd=["colmap"], timeout=10)
        mock_run.side_effect = timeout_exc
        with pytest.raises(RuntimeError) as exc_info:
            _run_colmap("mapper", [])
        assert exc_info.value.__cause__ is timeout_exc

    @patch("src.reconstruction.reconstruction.time.sleep")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    def test_max_retries_preserves_cause(self, mock_run, mock_sleep):
        """최대 재시도 소진 시에도 __cause__가 보존된다."""
        timeout_exc = subprocess.TimeoutExpired(cmd=["colmap"], timeout=10)
        mock_run.side_effect = timeout_exc
        config = ColmapRetryConfig(max_retries=1, base_delay=0.01)
        with pytest.raises(RuntimeError) as exc_info:
            _run_colmap("mapper", [], retry_config=config)
        assert exc_info.value.__cause__ is timeout_exc


class TestCheckpoint:
    """체크포인트 저장/로드 테스트."""

    def test_save_and_load(self, tmp_path):
        _save_checkpoint(tmp_path, "feature_extraction", ["feature_extraction"])
        cp = _load_checkpoint(tmp_path)
        assert cp is not None
        assert cp["last_completed_step"] == "feature_extraction"
        assert cp["steps_completed"] == ["feature_extraction"]

    def test_load_missing(self, tmp_path):
        assert _load_checkpoint(tmp_path) is None

    def test_load_corrupt(self, tmp_path):
        (tmp_path / "checkpoint.json").write_text("not json")
        assert _load_checkpoint(tmp_path) is None


class TestCleanupWorkspace:
    """_cleanup_workspace 테스트."""

    def test_removes_tmp_and_log_files(self, tmp_path):
        (tmp_path / "temp.tmp").write_text("tmp")
        (tmp_path / "output.log").write_text("log")
        (tmp_path / "important.ply").write_text("keep")
        _cleanup_workspace(tmp_path)
        assert not (tmp_path / "temp.tmp").exists()
        assert not (tmp_path / "output.log").exists()
        assert (tmp_path / "important.ply").exists()


class TestDenseCleanup:
    """Dense 단계 실패 시 cleanup 호출 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_dense_failure_triggers_cleanup(
        self,
        mock_colmap,
        mock_subprocess,
        tmp_path,
    ):
        """Dense reconstruction 실패 시 _cleanup_workspace가 호출된다."""
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(3):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"

        call_count = 0

        def side_effect(command, args, **kwargs):
            nonlocal call_count
            call_count += 1
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
                raise RuntimeError("Dense reconstruction 실패")
            return MagicMock(returncode=0)

        mock_colmap.side_effect = side_effect
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 3\nPoints 3D = 50\n",
        )

        # tmp 파일 생성 (cleanup 대상)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "temp.tmp").write_text("tmp")

        with pytest.raises(RuntimeError, match="Dense reconstruction 실패"):
            reconstruct(image_dir, workspace, dense=True)

        # cleanup이 호출되어 tmp 파일이 제거되었는지 확인
        assert not (workspace / "temp.tmp").exists()


class TestReconstructCheckpointResume:
    """체크포인트에서 재개하는 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_resume_from_checkpoint(self, mock_colmap, mock_subprocess, tmp_path):
        """feature_extraction이 완료된 체크포인트에서 재개."""
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(3):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)

        # 이전 실행에서 feature_extraction까지 완료된 상태 시뮬레이션
        db = workspace / "database.db"
        db.touch()
        _save_checkpoint(workspace, "feature_extraction", ["feature_extraction"])

        def side_effect(command, args, **kwargs):
            if command == "mapper":
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

        # feature_extractor는 호출되지 않아야 함 (체크포인트에서 건너뜀)
        colmap_commands = [c[0][0] for c in mock_colmap.call_args_list]
        assert "feature_extractor" not in colmap_commands
        assert "feature_extraction" in result.steps_completed
        assert "exhaustive_matching" in result.steps_completed
        assert "sparse_reconstruction" in result.steps_completed

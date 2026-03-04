"""3D Gaussian Splatting 파이프라인 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from src.reconstruction.gaussian_splatting import (
    GaussianSplattingResult,
    convert_colmap_to_nerfstudio,
    detect_vram_gb,
    run_gaussian_splatting,
    select_vram_preset,
    train_gaussian_splatting,
)


class TestDetectVramGb:
    """GPU VRAM 감지 테스트."""

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_nvidia_smi_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="12288\n")
        assert detect_vram_gb() == pytest.approx(12.0, rel=0.01)

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_nvidia_smi_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert detect_vram_gb() == 0.0

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_nvidia_smi_not_found(self, mock_run):
        mock_run.side_effect = OSError("command not found")
        assert detect_vram_gb() == 0.0


class TestSelectVramPreset:
    """VRAM 프리셋 선택 테스트."""

    def test_low_vram(self):
        assert select_vram_preset(6.0) == "low"
        assert select_vram_preset(8.0) == "low"

    def test_medium_vram(self):
        assert select_vram_preset(12.0) == "medium"
        assert select_vram_preset(16.0) == "medium"

    def test_high_vram(self):
        assert select_vram_preset(24.0) == "high"

    def test_zero_vram_defaults_medium(self):
        assert select_vram_preset(0.0) == "medium"

    def test_negative_vram_defaults_medium(self):
        assert select_vram_preset(-1.0) == "medium"


class TestConvertColmapToNerfstudio:
    """COLMAP → nerfstudio 변환 테스트."""

    def test_missing_sparse_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="COLMAP sparse"):
            convert_colmap_to_nerfstudio(missing, image_dir, tmp_path / "output")

    def test_missing_image_dir(self, tmp_path):
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError, match="이미지 디렉토리"):
            convert_colmap_to_nerfstudio(sparse_dir, missing, tmp_path / "output")

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_success(self, mock_run, tmp_path):
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        output_dir = tmp_path / "ns_data"

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = convert_colmap_to_nerfstudio(sparse_dir, image_dir, output_dir)

        assert result == output_dir
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "ns-process-data" in call_args
        assert "--skip-colmap" in call_args

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_failure_raises_runtime_error(self, mock_run, tmp_path):
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="conversion failed"
        )
        with pytest.raises(RuntimeError, match="nerfstudio 데이터 변환 실패"):
            convert_colmap_to_nerfstudio(sparse_dir, image_dir, tmp_path / "output")


class TestTrainGaussianSplatting:
    """3DGS 학습 테스트."""

    def test_missing_data_dir(self, tmp_path):
        missing = tmp_path / "nonexistent"
        with pytest.raises(FileNotFoundError, match="데이터 디렉토리"):
            train_gaussian_splatting(missing, tmp_path / "output")

    @patch("src.reconstruction.gaussian_splatting.detect_vram_gb")
    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_success_with_auto_preset(self, mock_run, mock_vram, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        output_dir = tmp_path / "output"

        mock_vram.return_value = 12.0
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # 출력 PLY 파일 생성 시뮬레이션
        def create_output(*args, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "point_cloud.ply").write_bytes(b"\x00" * 100)
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = create_output

        result = train_gaussian_splatting(data_dir, output_dir)

        assert isinstance(result, GaussianSplattingResult)
        assert result.vram_preset == "medium"
        assert result.num_iterations == 15000
        assert result.ply_path is not None

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_explicit_preset(self, mock_run, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        output_dir = tmp_path / "output"

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = train_gaussian_splatting(
            data_dir, output_dir, vram_preset="low", max_iterations=5000
        )

        assert result.vram_preset == "low"
        assert result.num_iterations == 5000

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_failure_raises_runtime_error(self, mock_run, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="training failed"
        )
        with pytest.raises(RuntimeError, match="3DGS 학습 실패"):
            train_gaussian_splatting(data_dir, tmp_path / "output", vram_preset="low")


class TestRunGaussianSplatting:
    """전체 3DGS 파이프라인 통합 테스트."""

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    def test_full_pipeline(self, mock_run, tmp_path):
        sparse_dir = tmp_path / "sparse"
        sparse_dir.mkdir()
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        workspace = tmp_path / "gs_workspace"

        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # train 단계: PLY 출력 생성
                gs_out = workspace / "gs_output"
                gs_out.mkdir(parents=True, exist_ok=True)
                (gs_out / "splat.ply").write_text(
                    "ply\nformat ascii 1.0\nelement vertex 1000\nend_header\n"
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        result = run_gaussian_splatting(
            sparse_dir, image_dir, workspace, vram_preset="low"
        )

        assert isinstance(result, GaussianSplattingResult)
        assert result.vram_preset == "low"
        # 메타데이터 파일 확인
        metadata_path = workspace / "gaussian_splatting_metadata.json"
        assert metadata_path.exists()


class TestReconstructWithGaussianSplatting:
    """reconstruct() 함수의 gaussian_splatting 옵션 테스트."""

    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_gs_disabled_no_gs_fields(self, mock_colmap, mock_subprocess, tmp_path):
        """gaussian_splatting=False일 때 GS 필드가 None인지 확인."""
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

        from src.reconstruction.reconstruction import reconstruct

        result = reconstruct(
            image_dir, workspace, export_ply=False, gaussian_splatting=False
        )

        assert result.gs_ply_path is None
        assert result.gs_splat_path is None
        assert result.gs_num_iterations is None
        assert "gaussian_splatting" not in result.steps_completed

    @patch("src.reconstruction.gaussian_splatting.subprocess.run")
    @patch("src.reconstruction.reconstruction.subprocess.run")
    @patch("src.reconstruction.reconstruction._run_colmap")
    def test_gs_enabled(
        self, mock_colmap, mock_recon_subprocess, mock_gs_subprocess, tmp_path
    ):
        """gaussian_splatting=True일 때 GS 학습이 실행되는지 확인."""
        image_dir = tmp_path / "images"
        image_dir.mkdir()
        for i in range(5):
            (image_dir / f"frame_{i:06d}.jpg").write_bytes(b"\xff" * 100)
        workspace = tmp_path / "workspace"

        def colmap_side_effect(command, args):
            if command == "feature_extractor":
                db = workspace / "database.db"
                db.parent.mkdir(parents=True, exist_ok=True)
                db.touch()
            elif command == "mapper":
                model_dir = workspace / "sparse" / "0"
                model_dir.mkdir(parents=True, exist_ok=True)
                (model_dir / "images.bin").write_bytes(b"\x00" * 1024)
                (model_dir / "points3D.bin").write_bytes(b"\x00" * 640)
            return MagicMock(returncode=0)

        mock_colmap.side_effect = colmap_side_effect

        # model_analyzer
        mock_recon_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="Registered images = 5\nPoints 3D = 120\n",
        )

        gs_call_count = 0

        def gs_side_effect(cmd, **kwargs):
            nonlocal gs_call_count
            gs_call_count += 1
            if gs_call_count == 2:
                # train: PLY 생성
                gs_out = workspace / "gaussian_splatting" / "gs_output"
                gs_out.mkdir(parents=True, exist_ok=True)
                (gs_out / "point_cloud.ply").write_text(
                    "ply\nformat ascii 1.0\nelement vertex 5000\nend_header\n"
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_gs_subprocess.side_effect = gs_side_effect

        from src.reconstruction.reconstruction import reconstruct

        result = reconstruct(
            image_dir,
            workspace,
            export_ply=False,
            gaussian_splatting=True,
            gs_max_iterations=1000,
        )

        assert "gaussian_splatting" in result.steps_completed
        assert result.gs_num_iterations == 1000
        assert result.gs_ply_path is not None

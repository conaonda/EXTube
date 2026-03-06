"""COLMAP 기반 3D 복원 파이프라인.

프레임 이미지 디렉토리를 입력받아 COLMAP SfM 파이프라인을 실행하고
sparse/dense 포인트 클라우드를 생성한다.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReconstructionResult:
    """3D 복원 결과."""

    workspace_dir: Path
    sparse_dir: Path
    num_images: int
    num_registered: int
    num_points3d: int
    camera_model: str = "SIMPLE_RADIAL"
    steps_completed: list[str] = field(default_factory=list)
    dense_dir: Path | None = None
    num_dense_points: int | None = None
    gs_ply_path: Path | None = None
    gs_splat_path: Path | None = None
    gs_num_iterations: int | None = None
    potree_metadata_path: Path | None = None


def _run_colmap(
    command: str,
    args: list[str],
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """COLMAP CLI 명령을 실행한다."""
    cmd = ["colmap", command, *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"COLMAP {command} 시간 초과 ({timeout}초). "
            f"이미지 수를 줄이거나 max_image_size를 설정해보세요."
        )
    if result.returncode != 0:
        raise RuntimeError(
            f"COLMAP {command} 실패 (code {result.returncode}): {result.stderr}"
        )
    return result


def feature_extractor(
    image_dir: Path,
    database_path: Path,
    camera_model: str = "SIMPLE_RADIAL",
) -> None:
    """이미지에서 특징점을 추출한다."""
    if not image_dir.is_dir():
        raise FileNotFoundError(f"이미지 디렉토리를 찾을 수 없습니다: {image_dir}")

    _run_colmap(
        "feature_extractor",
        [
            "--database_path",
            str(database_path),
            "--image_path",
            str(image_dir),
            "--ImageReader.camera_model",
            camera_model,
            "--ImageReader.single_camera",
            "1",
        ],
    )


def exhaustive_matcher(database_path: Path) -> None:
    """특징점 매칭을 수행한다."""
    if not database_path.is_file():
        raise FileNotFoundError(f"데이터베이스를 찾을 수 없습니다: {database_path}")

    _run_colmap(
        "exhaustive_matcher",
        ["--database_path", str(database_path)],
    )


def sparse_reconstructor(
    database_path: Path,
    image_dir: Path,
    output_dir: Path,
) -> None:
    """Sparse 3D 복원을 수행한다."""
    if not database_path.is_file():
        raise FileNotFoundError(f"데이터베이스를 찾을 수 없습니다: {database_path}")
    if not image_dir.is_dir():
        raise FileNotFoundError(f"이미지 디렉토리를 찾을 수 없습니다: {image_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    _run_colmap(
        "mapper",
        [
            "--database_path",
            str(database_path),
            "--image_path",
            str(image_dir),
            "--output_path",
            str(output_dir),
        ],
    )


def export_to_ply(
    sparse_model_dir: Path,
    output_path: Path,
) -> None:
    """Sparse 모델을 PLY 포맷으로 내보낸다."""
    if not sparse_model_dir.is_dir():
        raise FileNotFoundError(
            f"Sparse 모델 디렉토리를 찾을 수 없습니다: {sparse_model_dir}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    _run_colmap(
        "model_converter",
        [
            "--input_path",
            str(sparse_model_dir),
            "--output_path",
            str(output_path),
            "--output_type",
            "PLY",
        ],
    )


def image_undistorter(
    image_dir: Path,
    sparse_model_dir: Path,
    output_dir: Path,
    max_image_size: int = 0,
) -> None:
    """이미지 왜곡을 보정한다 (dense reconstruction 전처리)."""
    if not sparse_model_dir.is_dir():
        raise FileNotFoundError(
            f"Sparse 모델 디렉토리를 찾을 수 없습니다: {sparse_model_dir}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    args = [
        "--image_path",
        str(image_dir),
        "--input_path",
        str(sparse_model_dir),
        "--output_path",
        str(output_dir),
        "--output_type",
        "COLMAP",
    ]
    if max_image_size > 0:
        args.extend(["--max_image_size", str(max_image_size)])

    _run_colmap("image_undistorter", args)


def patch_match_stereo(
    workspace_dir: Path,
    max_image_size: int = 0,
) -> None:
    """PatchMatch 스테레오 매칭으로 깊이 맵을 생성한다."""
    if not workspace_dir.is_dir():
        raise FileNotFoundError(f"작업 디렉토리를 찾을 수 없습니다: {workspace_dir}")

    args = [
        "--workspace_path",
        str(workspace_dir),
        "--workspace_format",
        "COLMAP",
    ]
    if max_image_size > 0:
        args.extend(["--PatchMatchStereo.max_image_size", str(max_image_size)])

    _run_colmap("patch_match_stereo", args)


def stereo_fusion(
    workspace_dir: Path,
    output_path: Path,
) -> None:
    """깊이 맵을 융합하여 밀집 포인트 클라우드를 생성한다."""
    if not workspace_dir.is_dir():
        raise FileNotFoundError(f"작업 디렉토리를 찾을 수 없습니다: {workspace_dir}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    _run_colmap(
        "stereo_fusion",
        [
            "--workspace_path",
            str(workspace_dir),
            "--workspace_format",
            "COLMAP",
            "--output_path",
            str(output_path),
        ],
    )


def potree_convert(
    ply_path: Path,
    output_dir: Path,
    timeout: int = 600,
) -> Path | None:
    """PLY 파일을 PotreeConverter 2.x로 octree 포맷으로 변환한다.

    Returns:
        metadata.json 경로, 또는 PotreeConverter가 없으면 None
    """
    if not shutil.which("PotreeConverter"):
        return None

    if not ply_path.is_file():
        raise FileNotFoundError(f"PLY 파일을 찾을 수 없습니다: {ply_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "PotreeConverter",
        str(ply_path),
        "-o",
        str(output_dir),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"PotreeConverter 실패 (code {result.returncode}): {result.stderr}"
        )

    metadata_path = output_dir / "metadata.json"
    if metadata_path.exists():
        return metadata_path
    return None


def _count_ply_points(ply_path: Path) -> int:
    """PLY 파일의 vertex 수를 헤더에서 파싱한다."""
    try:
        with open(ply_path, "rb") as f:
            for raw_line in f:
                line = raw_line.decode("ascii", errors="ignore").strip()
                if line.startswith("element vertex"):
                    return int(line.split()[-1])
                if line == "end_header":
                    break
    except (OSError, ValueError):
        pass
    return 0


def _parse_reconstruction_stats(
    sparse_dir: Path,
    timeout: int = 60,
) -> dict:
    """Sparse 복원 결과에서 통계를 파싱한다.

    colmap model_analyzer를 사용하여 정확한 통계를 가져온다.
    """
    model_dirs = sorted(d for d in sparse_dir.iterdir() if d.is_dir())
    if not model_dirs:
        return {"num_registered": 0, "num_points3d": 0}

    model_dir = model_dirs[0]

    num_registered = 0
    num_points3d = 0

    try:
        result = subprocess.run(
            ["colmap", "model_analyzer", "--path", str(model_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        for line in result.stdout.split("\n"):
            if "Registered images" in line:
                num_registered = int(line.split("=")[-1].strip())
            elif "Points" in line and "3D" in line:
                num_points3d = int(line.split("=")[-1].strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass

    return {
        "num_registered": num_registered,
        "num_points3d": num_points3d,
        "model_dir": str(model_dir),
    }


def reconstruct(
    image_dir: Path,
    workspace_dir: Path,
    camera_model: str = "SIMPLE_RADIAL",
    export_ply: bool = True,
    timeout: int = 3600,
    dense: bool = False,
    max_image_size: int = 0,
    gaussian_splatting: bool = False,
    gs_max_iterations: int | None = None,
) -> ReconstructionResult:
    """전체 COLMAP SfM 파이프라인을 실행한다.

    Args:
        image_dir: 프레임 이미지가 있는 디렉토리
        workspace_dir: 작업 공간 디렉토리 (생성됨)
        camera_model: COLMAP 카메라 모델
        export_ply: PLY 파일 내보내기 여부
        timeout: COLMAP 명령 타임아웃 (초, 기본 3600)
        dense: Dense reconstruction (MVS) 실행 여부
        max_image_size: Dense reconstruction 최대 이미지 크기 (0=제한 없음)
        gaussian_splatting: 3D Gaussian Splatting 학습 실행 여부
        gs_max_iterations: 3DGS 최대 학습 반복 횟수 (None=자동)

    Returns:
        ReconstructionResult: 복원 결과

    Raises:
        FileNotFoundError: 이미지 디렉토리가 없는 경우
        RuntimeError: COLMAP 명령 실패 시
    """
    if not image_dir.is_dir():
        raise FileNotFoundError(f"이미지 디렉토리를 찾을 수 없습니다: {image_dir}")

    # 작업 공간 구성
    workspace_dir.mkdir(parents=True, exist_ok=True)
    database_path = workspace_dir / "database.db"
    sparse_dir = workspace_dir / "sparse"

    image_extensions = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
    images = []
    for ext in image_extensions:
        images.extend(image_dir.glob(ext))
    num_images = len(images)

    if num_images < 2:
        raise ValueError(f"최소 2장의 이미지가 필요합니다 (현재 {num_images}장)")

    steps_completed = []

    # 1. Feature extraction
    feature_extractor(image_dir, database_path, camera_model)
    steps_completed.append("feature_extraction")

    # 2. Feature matching
    exhaustive_matcher(database_path)
    steps_completed.append("exhaustive_matching")

    # 3. Sparse reconstruction
    sparse_reconstructor(database_path, image_dir, sparse_dir)
    steps_completed.append("sparse_reconstruction")

    # 통계 파싱 (1회만 호출)
    stats = _parse_reconstruction_stats(sparse_dir)

    if stats["num_points3d"] == 0:
        raise RuntimeError(
            "Sparse reconstruction에서 3D 포인트가 0개입니다. "
            "입력 이미지 간 시각적 중복이 부족하거나 품질이 낮을 수 있습니다."
        )

    # 4. PLY export
    if export_ply:
        model_dir = stats.get("model_dir")
        if model_dir:
            ply_path = workspace_dir / "points.ply"
            export_to_ply(Path(model_dir), ply_path)
            steps_completed.append("ply_export")

    # 5-7. Dense reconstruction (MVS)
    dense_dir = None
    num_dense_points = None
    if dense:
        model_dir = stats.get("model_dir")
        if model_dir:
            dense_ws = workspace_dir / "dense"
            image_undistorter(
                image_dir,
                Path(model_dir),
                dense_ws,
                max_image_size=max_image_size,
            )
            steps_completed.append("image_undistortion")

            patch_match_stereo(dense_ws, max_image_size=max_image_size)
            steps_completed.append("patch_match_stereo")

            dense_ply_path = workspace_dir / "dense_points.ply"
            stereo_fusion(dense_ws, dense_ply_path)
            steps_completed.append("stereo_fusion")

            dense_dir = dense_ws
            num_dense_points = _count_ply_points(dense_ply_path)

    # 8. 3D Gaussian Splatting 학습
    gs_ply_path = None
    gs_splat_path = None
    gs_num_iterations = None
    if gaussian_splatting:
        model_dir = stats.get("model_dir")
        if model_dir:
            from src.reconstruction.gaussian_splatting import run_gaussian_splatting

            gs_workspace = workspace_dir / "gaussian_splatting"
            gs_result = run_gaussian_splatting(
                Path(model_dir),
                image_dir,
                gs_workspace,
                max_iterations=gs_max_iterations,
            )
            steps_completed.append("gaussian_splatting")
            gs_ply_path = gs_result.ply_path
            gs_splat_path = gs_result.splat_path
            gs_num_iterations = gs_result.num_iterations

    # 9. Potree octree 변환 (PotreeConverter가 있는 경우)
    potree_metadata_path = None
    # dense PLY가 있으면 그것을 변환, 없으면 sparse PLY
    potree_source_ply = None
    if dense and (workspace_dir / "dense_points.ply").exists():
        potree_source_ply = workspace_dir / "dense_points.ply"
    elif (workspace_dir / "points.ply").exists():
        potree_source_ply = workspace_dir / "points.ply"

    if potree_source_ply:
        potree_dir = workspace_dir / "potree"
        potree_metadata_path = potree_convert(potree_source_ply, potree_dir)
        if potree_metadata_path:
            steps_completed.append("potree_conversion")

    # 메타데이터 저장
    metadata = {
        "image_dir": str(image_dir),
        "workspace_dir": str(workspace_dir),
        "num_images": num_images,
        "num_registered": stats["num_registered"],
        "num_points3d": stats["num_points3d"],
        "camera_model": camera_model,
        "steps_completed": steps_completed,
    }
    if dense and num_dense_points is not None:
        metadata["num_dense_points"] = num_dense_points
    if gaussian_splatting and gs_num_iterations is not None:
        metadata["gs_num_iterations"] = gs_num_iterations
        metadata["gs_ply_path"] = str(gs_ply_path) if gs_ply_path else None
        metadata["gs_splat_path"] = str(gs_splat_path) if gs_splat_path else None
    if potree_metadata_path:
        metadata["potree_metadata_path"] = str(potree_metadata_path)
    metadata_path = workspace_dir / "reconstruction_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    return ReconstructionResult(
        workspace_dir=workspace_dir,
        sparse_dir=sparse_dir,
        num_images=num_images,
        num_registered=stats["num_registered"],
        num_points3d=stats["num_points3d"],
        camera_model=camera_model,
        steps_completed=steps_completed,
        dense_dir=dense_dir,
        num_dense_points=num_dense_points,
        gs_ply_path=gs_ply_path,
        gs_splat_path=gs_splat_path,
        gs_num_iterations=gs_num_iterations,
        potree_metadata_path=potree_metadata_path,
    )

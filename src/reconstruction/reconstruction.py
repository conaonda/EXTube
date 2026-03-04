"""COLMAP 기반 3D 복원 파이프라인.

프레임 이미지 디렉토리를 입력받아 COLMAP SfM 파이프라인을 실행하고
sparse/dense 포인트 클라우드를 생성한다.
"""

import json
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


def _run_colmap(
    command: str,
    args: list[str],
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """COLMAP CLI 명령을 실행한다."""
    cmd = ["colmap", command, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
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
) -> ReconstructionResult:
    """전체 COLMAP SfM 파이프라인을 실행한다.

    Args:
        image_dir: 프레임 이미지가 있는 디렉토리
        workspace_dir: 작업 공간 디렉토리 (생성됨)
        camera_model: COLMAP 카메라 모델
        export_ply: PLY 파일 내보내기 여부
        timeout: COLMAP 명령 타임아웃 (초, 기본 3600)

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

    # 4. PLY export
    if export_ply:
        model_dir = stats.get("model_dir")
        if model_dir:
            ply_path = workspace_dir / "points.ply"
            export_to_ply(Path(model_dir), ply_path)
            steps_completed.append("ply_export")

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
    )

"""nerfstudio + gsplat 기반 3D Gaussian Splatting 학습 파이프라인.

COLMAP sparse 복원 결과를 입력받아 splatfacto 모델을 학습하고
.ply / .splat 형식으로 출력한다.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# GPU VRAM별 학습 파라미터 프리셋
_VRAM_PRESETS: dict[str, dict] = {
    "low": {  # ≤8 GB
        "max_num_iterations": 7000,
        "steps_per_eval_image": 500,
        "pipeline.model.num_downscales": 2,
        "pipeline.model.cull_alpha_thresh": 0.005,
    },
    "medium": {  # 9-19 GB
        "max_num_iterations": 15000,
        "steps_per_eval_image": 500,
        "pipeline.model.num_downscales": 1,
        "pipeline.model.cull_alpha_thresh": 0.005,
    },
    "high": {  # 20+ GB
        "max_num_iterations": 30000,
        "steps_per_eval_image": 1000,
        "pipeline.model.num_downscales": 0,
        "pipeline.model.cull_alpha_thresh": 0.005,
    },
}

_TIMEOUT_SENTINEL = object()

_OOM_PATTERNS = ("CUDA out of memory", "OutOfMemoryError")


@dataclass
class GaussianSplattingResult:
    """3D Gaussian Splatting 학습 결과."""

    output_dir: Path
    ply_path: Path | None = None
    splat_path: Path | None = None
    num_iterations: int = 0
    vram_preset: str = "medium"


def detect_vram_gb() -> float:
    """GPU VRAM 크기를 GB 단위로 감지한다.

    Returns:
        VRAM 크기 (GB). 감지 실패 시 0.0 반환.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # 첫 번째 GPU의 VRAM (MiB → GB)
            mib = float(result.stdout.strip().split("\n")[0])
            return mib / 1024.0
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return 0.0


def detect_vram_free_gb() -> float:
    """현재 사용 가능한 GPU VRAM(GB)을 감지한다."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            mib = float(result.stdout.strip().split("\n")[0])
            return mib / 1024.0
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return 0.0


def compute_dynamic_timeout(vram_gb: float, num_iterations: int) -> int:
    """VRAM과 iteration 수 기반으로 동적 타임아웃을 계산한다."""
    base = 1800
    if vram_gb <= 8:
        per_iter = 0.5
    elif vram_gb < 20:
        per_iter = 0.3
    else:
        per_iter = 0.2
    return min(base + int(num_iterations * per_iter), 14400)


def select_vram_preset(vram_gb: float) -> str:
    """VRAM 크기에 따라 학습 프리셋을 선택한다.

    Args:
        vram_gb: GPU VRAM 크기 (GB)

    Returns:
        프리셋 이름: "low", "medium", "high"
    """
    if vram_gb <= 0:
        return "medium"
    if vram_gb <= 8:
        return "low"
    if vram_gb < 20:
        return "medium"
    return "high"


def convert_colmap_to_nerfstudio(
    colmap_sparse_dir: Path,
    image_dir: Path,
    output_dir: Path,
) -> Path:
    """COLMAP sparse 출력을 nerfstudio 데이터 형식으로 변환한다.

    Args:
        colmap_sparse_dir: COLMAP sparse 모델 디렉토리 (예: sparse/0)
        image_dir: 원본 이미지 디렉토리
        output_dir: nerfstudio 데이터 출력 디렉토리

    Returns:
        변환된 데이터 디렉토리 경로

    Raises:
        FileNotFoundError: 입력 디렉토리가 없는 경우
        RuntimeError: 변환 실패 시
    """
    if not colmap_sparse_dir.is_dir():
        raise FileNotFoundError(
            f"COLMAP sparse 디렉토리를 찾을 수 없습니다: {colmap_sparse_dir}"
        )
    if not image_dir.is_dir():
        raise FileNotFoundError(f"이미지 디렉토리를 찾을 수 없습니다: {image_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ns-process-data",
        "images",
        "--data",
        str(image_dir),
        "--output-dir",
        str(output_dir),
        "--colmap-model-path",
        str(colmap_sparse_dir),
        "--skip-colmap",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nerfstudio 데이터 변환 실패 (code {result.returncode}): {result.stderr}"
        )

    return output_dir


def _is_oom_error(stderr: str) -> bool:
    """stderr에 OOM 관련 에러 패턴이 있는지 확인한다."""
    return any(pattern in stderr for pattern in _OOM_PATTERNS)


def train_gaussian_splatting(
    data_dir: Path,
    output_dir: Path,
    *,
    vram_preset: str | None = None,
    max_iterations: int | None = None,
    timeout: int | None = None,
    on_oom_callback: Callable[[str], None] | None = None,
) -> GaussianSplattingResult:
    """splatfacto 모델을 학습한다.

    Args:
        data_dir: nerfstudio 형식 데이터 디렉토리
        output_dir: 학습 출력 디렉토리
        vram_preset: VRAM 프리셋 ("low", "medium", "high"). None이면 자동 감지.
        max_iterations: 최대 학습 반복 횟수. None이면 프리셋 기본값 사용.
        timeout: 학습 타임아웃 (초). None이면 동적 계산.
        on_oom_callback: OOM 발생 시 호출되는 콜백. 메시지 문자열을 인자로 받는다.

    Returns:
        GaussianSplattingResult: 학습 결과

    Raises:
        FileNotFoundError: 데이터 디렉토리가 없는 경우
        RuntimeError: 학습 실패 시
    """
    if not data_dir.is_dir():
        raise FileNotFoundError(f"데이터 디렉토리를 찾을 수 없습니다: {data_dir}")

    # VRAM 프리셋 결정
    if vram_preset is None:
        vram_gb = detect_vram_gb()
        vram_preset = select_vram_preset(vram_gb)
        logger.info("GPU VRAM: %.1f GB → 프리셋: %s", vram_gb, vram_preset)
    else:
        vram_gb = detect_vram_gb()

    preset = _VRAM_PRESETS.get(vram_preset, _VRAM_PRESETS["medium"])
    iterations = (
        max_iterations if max_iterations is not None else preset["max_num_iterations"]
    )

    # 동적 타임아웃 계산
    if timeout is None:
        timeout = compute_dynamic_timeout(vram_gb, iterations)
        logger.info(
            "동적 타임아웃: %d초 (VRAM=%.1fGB, iters=%d)", timeout, vram_gb, iterations
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    def _build_cmd(iters: int) -> list[str]:
        return [
            "ns-train",
            "splatfacto",
            "--data",
            str(data_dir),
            "--output-dir",
            str(output_dir),
            "--max-num-iterations",
            str(iters),
            "--steps-per-eval-image",
            str(preset["steps_per_eval_image"]),
            f"--pipeline.model.num-downscales={preset['pipeline.model.num_downscales']}",
            f"--pipeline.model.cull-alpha-thresh={preset['pipeline.model.cull_alpha_thresh']}",
        ]

    logger.info("3DGS 학습 시작: %d iterations, 프리셋=%s", iterations, vram_preset)
    result = subprocess.run(
        _build_cmd(iterations),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )

    if result.returncode != 0 and _is_oom_error(result.stderr):
        # OOM 감지: iteration 50% 감소 후 재시도
        reduced_iterations = iterations // 2
        oom_msg = (
            f"OOM 감지: iteration {iterations} → {reduced_iterations}로 감소 후 재시도"
        )
        logger.warning(oom_msg)
        if on_oom_callback is not None:
            on_oom_callback(oom_msg)

        result = subprocess.run(
            _build_cmd(reduced_iterations),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        if result.returncode != 0 and _is_oom_error(result.stderr):
            raise RuntimeError(
                f"GPU VRAM이 부족합니다. "
                f"{reduced_iterations} iterations에서도 OOM이 발생했습니다. "
                f"더 낮은 해상도나 적은 iteration을 사용하세요."
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"3DGS 학습 실패 (code {result.returncode}): {result.stderr}"
            )

        iterations = reduced_iterations
    elif result.returncode != 0:
        raise RuntimeError(
            f"3DGS 학습 실패 (code {result.returncode}): {result.stderr}"
        )

    # 출력 파일 탐색
    ply_path = _find_output_file(output_dir, "*.ply")
    splat_path = _find_output_file(output_dir, "*.splat")

    return GaussianSplattingResult(
        output_dir=output_dir,
        ply_path=ply_path,
        splat_path=splat_path,
        num_iterations=iterations,
        vram_preset=vram_preset,
    )


def run_gaussian_splatting(
    colmap_sparse_dir: Path,
    image_dir: Path,
    workspace_dir: Path,
    *,
    vram_preset: str | None = None,
    max_iterations: int | None = None,
    timeout: int = 7200,
) -> GaussianSplattingResult:
    """COLMAP sparse 결과에서 3DGS 학습까지 전체 흐름을 실행한다.

    Args:
        colmap_sparse_dir: COLMAP sparse 모델 디렉토리 (예: sparse/0)
        image_dir: 원본 이미지 디렉토리
        workspace_dir: 작업 디렉토리
        vram_preset: VRAM 프리셋. None이면 자동 감지.
        max_iterations: 최대 학습 반복 횟수.
        timeout: 학습 타임아웃 (초)

    Returns:
        GaussianSplattingResult: 학습 결과

    Raises:
        FileNotFoundError: 입력 디렉토리가 없는 경우
        RuntimeError: 파이프라인 실패 시
    """
    # 1. COLMAP → nerfstudio 데이터 변환
    ns_data_dir = workspace_dir / "ns_data"
    logger.info("COLMAP → nerfstudio 데이터 변환 중...")
    convert_colmap_to_nerfstudio(colmap_sparse_dir, image_dir, ns_data_dir)

    # 2. 3DGS 학습
    gs_output_dir = workspace_dir / "gs_output"
    logger.info("3DGS 학습 시작...")
    gs_result = train_gaussian_splatting(
        ns_data_dir,
        gs_output_dir,
        vram_preset=vram_preset,
        max_iterations=max_iterations,
        timeout=timeout,
    )

    # 3. 결과 파일을 workspace로 복사
    final_ply = workspace_dir / "gaussian_splat.ply"
    final_splat = workspace_dir / "gaussian_splat.splat"

    if gs_result.ply_path and gs_result.ply_path.exists():
        shutil.copy2(gs_result.ply_path, final_ply)
        gs_result.ply_path = final_ply

    if gs_result.splat_path and gs_result.splat_path.exists():
        shutil.copy2(gs_result.splat_path, final_splat)
        gs_result.splat_path = final_splat

    # 4. 메타데이터 저장
    metadata = {
        "vram_preset": gs_result.vram_preset,
        "num_iterations": gs_result.num_iterations,
        "ply_path": str(gs_result.ply_path) if gs_result.ply_path else None,
        "splat_path": str(gs_result.splat_path) if gs_result.splat_path else None,
    }
    metadata_path = workspace_dir / "gaussian_splatting_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    return gs_result


def _find_output_file(output_dir: Path, pattern: str) -> Path | None:
    """출력 디렉토리에서 패턴에 맞는 파일을 찾는다."""
    files = list(output_dir.rglob(pattern))
    if files:
        # 가장 최근 파일 반환
        return max(files, key=lambda f: f.stat().st_mtime)
    return None

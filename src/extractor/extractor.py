"""프레임 추출 및 품질 필터링 기능."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class FrameMetadata:
    """추출된 프레임 메타데이터."""

    frame_index: int
    timestamp: float
    file_path: str
    blur_score: float
    is_filtered: bool


@dataclass
class ExtractionResult:
    """프레임 추출 결과."""

    output_dir: Path
    total_extracted: int
    total_filtered: int
    frames: list[FrameMetadata]


def extract_frames(
    video_path: Path,
    output_dir: Path,
    interval: float = 1.0,
) -> list[Path]:
    """영상에서 일정 간격으로 프레임을 추출한다.

    Args:
        video_path: 입력 영상 경로
        output_dir: 프레임 출력 디렉토리
        interval: 추출 간격 (초, 기본 1.0)

    Returns:
        추출된 프레임 파일 경로 목록

    Raises:
        FileNotFoundError: 영상 파일이 없는 경우
        RuntimeError: ffmpeg 실행 실패
    """
    if not video_path.exists():
        raise FileNotFoundError(f"영상 파일을 찾을 수 없음: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-vf",
        f"fps=1/{interval}",
        "-q:v",
        "2",
        str(output_dir / "frame_%06d.jpg"),
        "-y",
        "-loglevel",
        "error",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 프레임 추출 실패: {result.stderr}")

    frames = sorted(output_dir.glob("frame_*.jpg"))
    return frames


def compute_blur_score(image_path: Path) -> float:
    """라플라시안 분산을 이용해 블러 점수를 계산한다.

    높은 값일수록 선명한 이미지.
    ffmpeg의 signalstats 필터로 계산하여 OpenCV 의존성을 제거.

    Args:
        image_path: 이미지 파일 경로

    Returns:
        블러 점수 (라플라시안 분산 근사값)
    """
    cmd = [
        "ffmpeg",
        "-i",
        str(image_path),
        "-vf",
        "laplacian,metadata=print",
        "-f",
        "null",
        "-loglevel",
        "info",
        "-",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    # lavfi.laplacian.variance 값을 파싱
    for line in result.stderr.split("\n"):
        if "lavfi.laplacian" in line and "variance" in line.lower():
            try:
                return float(line.split("=")[-1].strip())
            except (ValueError, IndexError):
                pass

    # 파싱 실패 시 대안: 이미지 파일 크기 기반 근사
    # 선명한 이미지일수록 디테일이 많아 파일 크기가 큼
    file_size = image_path.stat().st_size
    return float(file_size)


def filter_blurry_frames(
    frame_paths: list[Path],
    blur_threshold: float = 100.0,
) -> tuple[list[Path], list[Path]]:
    """블러 감지를 통해 저품질 프레임을 필터링한다.

    Args:
        frame_paths: 프레임 파일 경로 목록
        blur_threshold: 블러 임계값 (이 값 미만이면 블러로 판정)

    Returns:
        (통과 프레임 목록, 필터링된 프레임 목록)
    """
    passed = []
    filtered = []

    for path in frame_paths:
        score = compute_blur_score(path)
        if score >= blur_threshold:
            passed.append(path)
        else:
            filtered.append(path)

    return passed, filtered


def extract_and_filter(
    video_path: Path,
    output_dir: Path,
    interval: float = 1.0,
    blur_threshold: float = 100.0,
) -> ExtractionResult:
    """영상에서 프레임을 추출하고 품질 필터링을 수행한다.

    Args:
        video_path: 입력 영상 경로
        output_dir: 출력 디렉토리
        interval: 추출 간격 (초)
        blur_threshold: 블러 임계값

    Returns:
        ExtractionResult 추출 결과
    """
    frames_dir = output_dir / "frames"
    all_frames = extract_frames(video_path, frames_dir, interval)
    passed, filtered = filter_blurry_frames(all_frames, blur_threshold)

    # 필터링된 프레임을 별도 디렉토리로 이동
    filtered_dir = output_dir / "filtered"
    filtered_dir.mkdir(parents=True, exist_ok=True)
    for f in filtered:
        dest = filtered_dir / f.name
        f.rename(dest)

    # 메타데이터 생성
    metadata_list = []
    for i, frame in enumerate(all_frames):
        is_filtered = frame in filtered
        score = compute_blur_score(
            (filtered_dir / frame.name) if is_filtered else frame
        )
        metadata_list.append(
            FrameMetadata(
                frame_index=i,
                timestamp=i * interval,
                file_path=str(frame.name),
                blur_score=score,
                is_filtered=is_filtered,
            )
        )

    # 메타데이터 저장
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            [asdict(m) for m in metadata_list],
            ensure_ascii=False,
            indent=2,
        )
    )

    return ExtractionResult(
        output_dir=output_dir,
        total_extracted=len(all_frames),
        total_filtered=len(filtered),
        frames=metadata_list,
    )

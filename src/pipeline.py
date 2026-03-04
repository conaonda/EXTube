"""엔드투엔드 파이프라인 오케스트레이터.

유튜브 URL → 영상 다운로드 → 프레임 추출 → 3D 복원 전체 흐름을 관리한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.downloader import download_video, validate_youtube_url
from src.extractor import ExtractionResult, extract_and_filter
from src.reconstruction import ReconstructionResult, reconstruct

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""

    video_path: Path
    video_title: str
    extraction: ExtractionResult
    reconstruction: ReconstructionResult
    output_dir: Path


class Pipeline:
    """유튜브 영상 → 3D 복원 엔드투엔드 파이프라인."""

    def __init__(
        self,
        output_dir: Path,
        *,
        max_height: int = 1080,
        frame_interval: float = 1.0,
        blur_threshold: float = 100.0,
        camera_model: str = "SIMPLE_RADIAL",
        export_ply: bool = True,
        dense: bool = False,
        max_image_size: int = 0,
    ) -> None:
        self.output_dir = output_dir
        self.max_height = max_height
        self.frame_interval = frame_interval
        self.blur_threshold = blur_threshold
        self.camera_model = camera_model
        self.export_ply = export_ply
        self.dense = dense
        self.max_image_size = max_image_size

    def run(self, url: str) -> PipelineResult:
        """전체 파이프라인을 실행한다.

        Args:
            url: 유튜브 URL

        Returns:
            PipelineResult: 파이프라인 실행 결과

        Raises:
            ValueError: 유효하지 않은 URL
            RuntimeError: 파이프라인 단계 실패
        """
        if not validate_youtube_url(url):
            raise ValueError(f"유효하지 않은 유튜브 URL: {url}")

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. 다운로드
        logger.info("1/3 영상 다운로드 중: %s", url)
        download_dir = self.output_dir / "download"
        download_result = download_video(url, download_dir, max_height=self.max_height)
        logger.info(
            "다운로드 완료: %s (%s)",
            download_result.title,
            download_result.resolution,
        )

        # 2. 프레임 추출
        logger.info("2/3 프레임 추출 중...")
        extraction_dir = self.output_dir / "extraction"
        extraction_result = extract_and_filter(
            download_result.video_path,
            extraction_dir,
            interval=self.frame_interval,
            blur_threshold=self.blur_threshold,
        )
        total = extraction_result.total_extracted
        num_passed = total - extraction_result.total_filtered
        logger.info(
            "프레임 추출 완료: %d장 추출, %d장 통과, %d장 필터링",
            extraction_result.total_extracted,
            num_passed,
            extraction_result.total_filtered,
        )

        # 3. 3D 복원
        mode = "sparse+dense" if self.dense else "sparse"
        logger.info("3/3 3D 복원 중 (%s)...", mode)
        reconstruction_dir = self.output_dir / "reconstruction"
        frames_dir = extraction_dir / "frames"
        reconstruction_result = reconstruct(
            frames_dir,
            reconstruction_dir,
            camera_model=self.camera_model,
            export_ply=self.export_ply,
            dense=self.dense,
            max_image_size=self.max_image_size,
        )
        logger.info(
            "3D 복원 완료: %d/%d 이미지 등록, %d개 3D 포인트",
            reconstruction_result.num_registered,
            reconstruction_result.num_images,
            reconstruction_result.num_points3d,
        )

        return PipelineResult(
            video_path=download_result.video_path,
            video_title=download_result.title,
            extraction=extraction_result,
            reconstruction=reconstruction_result,
            output_dir=self.output_dir,
        )

"""EXTube CLI 진입점.

Usage:
    python -m src <youtube_url> [--output-dir DIR] [options]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.pipeline import Pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        prog="extube",
        description="유튜브 영상에서 3D 공간을 복원합니다.",
    )
    parser.add_argument("url", help="유튜브 URL")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="출력 디렉토리 (기본: output)",
    )
    parser.add_argument(
        "--max-height",
        type=int,
        default=1080,
        help="최대 영상 해상도 높이 (기본: 1080)",
    )
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=1.0,
        help="프레임 추출 간격 초 (기본: 1.0)",
    )
    parser.add_argument(
        "--blur-threshold",
        type=float,
        default=100.0,
        help="블러 필터링 임계값 (기본: 100.0)",
    )
    parser.add_argument(
        "--camera-model",
        default="SIMPLE_RADIAL",
        help="COLMAP 카메라 모델 (기본: SIMPLE_RADIAL)",
    )
    parser.add_argument(
        "--no-ply",
        action="store_true",
        help="PLY 파일 내보내기 비활성화",
    )
    parser.add_argument(
        "--dense",
        action="store_true",
        help="Dense reconstruction (MVS) 활성화",
    )
    parser.add_argument(
        "--max-image-size",
        type=int,
        default=0,
        help="Dense reconstruction 최대 이미지 크기 (0=제한 없음)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="상세 로깅 활성화",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 메인 함수."""
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    pipeline = Pipeline(
        output_dir=args.output_dir,
        max_height=args.max_height,
        frame_interval=args.frame_interval,
        blur_threshold=args.blur_threshold,
        camera_model=args.camera_model,
        export_ply=not args.no_ply,
        dense=args.dense,
        max_image_size=args.max_image_size,
    )

    try:
        result = pipeline.run(args.url)
    except ValueError as e:
        logging.error("입력 오류: %s", e)
        return 1
    except (RuntimeError, FileNotFoundError) as e:
        logging.error("파이프라인 실패: %s", e)
        return 1

    print(f"\n완료! 결과: {result.output_dir}")
    print(f"  영상: {result.video_title}")
    print(f"  프레임: {result.extraction.total_extracted}장 추출")
    print(f"  3D 포인트: {result.reconstruction.num_points3d}개")

    ply_path = result.reconstruction.workspace_dir / "points.ply"
    if ply_path.exists():
        print(f"  PLY 파일: {ply_path}")

    if result.reconstruction.num_dense_points is not None:
        print(f"  Dense 포인트: {result.reconstruction.num_dense_points}개")
        dense_ply = result.reconstruction.workspace_dir / "dense_points.ply"
        if dense_ply.exists():
            print(f"  Dense PLY 파일: {dense_ply}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Job 생성 파라미터 입력 검증 테스트."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.api.routers.jobs import JobCreate

_VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class TestFrameInterval:
    """frame_interval 범위 검증."""

    def test_below_min(self):
        with pytest.raises(ValidationError, match="frame_interval"):
            JobCreate(url=_VALID_URL, frame_interval=0.05)

    def test_above_max(self):
        with pytest.raises(ValidationError, match="frame_interval"):
            JobCreate(url=_VALID_URL, frame_interval=301)

    def test_valid_bounds(self):
        job = JobCreate(url=_VALID_URL, frame_interval=0.1)
        assert job.frame_interval == 0.1
        job = JobCreate(url=_VALID_URL, frame_interval=300)
        assert job.frame_interval == 300


class TestBlurThreshold:
    """blur_threshold 범위 검증."""

    def test_negative(self):
        with pytest.raises(ValidationError, match="blur_threshold"):
            JobCreate(url=_VALID_URL, blur_threshold=-1)

    def test_above_max(self):
        with pytest.raises(ValidationError, match="blur_threshold"):
            JobCreate(url=_VALID_URL, blur_threshold=501)

    def test_valid(self):
        job = JobCreate(url=_VALID_URL, blur_threshold=0)
        assert job.blur_threshold == 0
        job = JobCreate(url=_VALID_URL, blur_threshold=500)
        assert job.blur_threshold == 500


class TestCameraModel:
    """camera_model 화이트리스트 검증."""

    def test_invalid_model(self):
        with pytest.raises(ValidationError, match="지원하지 않는 카메라 모델"):
            JobCreate(url=_VALID_URL, camera_model="INVALID")

    def test_valid_models(self):
        for model in ("SIMPLE_RADIAL", "PINHOLE", "OPENCV"):
            job = JobCreate(url=_VALID_URL, camera_model=model)
            assert job.camera_model == model


class TestGsMaxIterations:
    """gs_max_iterations 범위 검증."""

    def test_zero(self):
        with pytest.raises(ValidationError, match="gs_max_iterations"):
            JobCreate(url=_VALID_URL, gs_max_iterations=0)

    def test_above_max(self):
        with pytest.raises(ValidationError, match="gs_max_iterations"):
            JobCreate(url=_VALID_URL, gs_max_iterations=100_001)

    def test_valid(self):
        job = JobCreate(url=_VALID_URL, gs_max_iterations=1)
        assert job.gs_max_iterations == 1
        job = JobCreate(url=_VALID_URL, gs_max_iterations=100_000)
        assert job.gs_max_iterations == 100_000

    def test_none_allowed(self):
        job = JobCreate(url=_VALID_URL)
        assert job.gs_max_iterations is None

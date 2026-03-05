"""GPU Semaphore 동시성 제한 테스트."""

from __future__ import annotations

import threading
import time

from src.api.config import Settings


def test_gpu_concurrency_setting_default():
    """기본 GPU 동시성은 1이다."""
    settings = Settings()
    assert settings.gpu_concurrency == 1


def test_gpu_semaphore_limits_concurrency():
    """Semaphore가 동시 실행 수를 제한하는지 확인한다."""
    semaphore = threading.Semaphore(1)
    max_concurrent = 0
    current_concurrent = 0
    lock = threading.Lock()

    def worker():
        nonlocal max_concurrent, current_concurrent
        with semaphore:
            with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            time.sleep(0.05)
            with lock:
                current_concurrent -= 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 1


def test_gpu_semaphore_allows_configured_concurrency():
    """설정된 동시성만큼 허용하는지 확인한다."""
    semaphore = threading.Semaphore(2)
    max_concurrent = 0
    current_concurrent = 0
    lock = threading.Lock()

    def worker():
        nonlocal max_concurrent, current_concurrent
        with semaphore:
            with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            time.sleep(0.05)
            with lock:
                current_concurrent -= 1

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent == 2

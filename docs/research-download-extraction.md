# 유튜브 영상 다운로드 및 프레임 추출 방법 조사

> 조사 기준일: 2026-03-05
> 관련 이슈: #2

## 1. yt-dlp 권장 설정

사진측량에서는 **압축 아티팩트 최소화**와 **최대 해상도 확보**가 핵심.

```bash
yt-dlp \
  -f "bestvideo[height>=1080]+bestaudio/bestvideo+bestaudio" \
  -S "res:2160,fps,br" \
  --merge-output-format mp4 \
  -o "%(id)s.%(ext)s" \
  <URL>
```

| 옵션 | 값 | 설명 |
|------|----|------|
| `-f` | `bestvideo+bestaudio` | 최고 화질 비디오+오디오 별도 스트림 |
| `-S` | `res:2160,fps,br` | 해상도 > fps > 비트레이트 순 정렬 |
| `--merge-output-format` | `mp4` | ffmpeg로 MP4 컨테이너 병합 |

> YouTube 4K는 VP9/AV1만 제공되는 경우가 많으므로 코덱 제한 없이 `bestvideo` 폴백.

## 2. 프레임 추출 방법 비교

| 방법 | 추출 품질 | 처리 속도 | 사진측량 복원 품질 | 권장 상황 |
|------|-----------|-----------|-------------------|-----------|
| **균일 샘플링** | 중간 | 빠름 | 중간 | 빠른 프로토타입 |
| **키프레임 추출** | 높음 | 매우 빠름 | 낮음 (간격 불균일) | 씬 컷 감지 |
| **씬 변화 감지** | 높음 | 중간 | 높음 | 씬 전환 많은 영상 |
| **하이브리드 (균일 + 필터링)** | 가장 높음 | 느림 | **가장 높음** | **사진측량 프로덕션 [권장]** |

### ffmpeg 명령어

```bash
# 균일 샘플링 (2fps)
ffmpeg -i input.mp4 -vf "fps=2" -q:v 1 frames/frame_%06d.jpg

# 키프레임만 추출
ffmpeg -i input.mp4 -vf "select='eq(pict_type,I)'" -vsync vfr -q:v 1 frames/keyframe_%06d.jpg

# 씬 변화 감지 (threshold=0.3)
ffmpeg -i input.mp4 -vf "select='gt(scene,0.3)'" -vsync vfr -q:v 1 frames/scene_%06d.jpg
```

## 3. 권장 프레임 필터링 파이프라인

```
영상 다운로드 → 균일 샘플링 (2~5fps) → 블러 감지 제거 → 중복 프레임 제거 → 오버랩 추정 → 최종 프레임셋
```

### 블러 감지: Laplacian Variance

```python
import cv2

def is_blurry(image_path: str, threshold: float = 100.0) -> bool:
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    return cv2.Laplacian(img, cv2.CV_64F).var() < threshold
```

### 중복 제거: 퍼셉추얼 해시 (pHash)

```python
import imagehash
from PIL import Image

def deduplicate_frames(frame_paths, hash_threshold=10):
    kept, last_hash = [], None
    for path in sorted(frame_paths):
        h = imagehash.phash(Image.open(path))
        if last_hash is None or (h - last_hash) > hash_threshold:
            kept.append(path)
            last_hash = h
    return kept
```

### 오버랩 추정: SSIM 기반

- 인접 프레임 유사도 0.5~0.85 범위 유지
- 너무 유사(>0.85): 중복 제거
- 너무 다름(<0.3): 급격한 카메라 이동 (매칭 실패 위험)

## 4. 통합 권장 설정값

| 파라미터 | 권장값 | 근거 |
|----------|--------|------|
| 다운로드 해상도 | 1080p 최소, 4K 선호 | COLMAP 등록률 향상 |
| 프레임 추출 fps | 2~5 fps | 2분 영상 기준 약 300프레임 목표 |
| 블러 임계값 (Laplacian) | 100~150 | 영상 종류에 따라 튜닝 |
| pHash 해밍 거리 | 8~12 | 낮을수록 엄격한 중복 제거 |
| 오버랩 범위 (SSIM) | 0.5~0.85 | 70~80% 오버랩이 최적 |
| 출력 이미지 포맷 | PNG (무손실) 또는 JPEG q=95+ | 추가 압축 손실 방지 |

## 참고 자료

- [yt-dlp 공식 저장소](https://github.com/yt-dlp/yt-dlp)
- [FFmpeg Frame Extraction Guide](https://ottverse.com/extract-frames-using-ffmpeg-a-comprehensive-guide/)
- [Blur Detection with OpenCV](https://pyimagesearch.com/2015/09/07/blur-detection-with-opencv/)
- [Pix4D Best Practices](https://support.pix4d.com/hc/best-practices-for-image-acquisition-and-photogrammetry)

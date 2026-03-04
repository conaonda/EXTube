# EXTube

유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 영상 속 3차원 공간을 복원하는 서비스입니다.

## 개요

유튜브 URL을 입력하면 영상에서 프레임을 추출하고, Structure-from-Motion(SfM) 또는 3D Gaussian Splatting 기술로 3D 공간을 복원하여 웹 브라우저에서 탐색할 수 있습니다.

## 파이프라인

```
유튜브 URL → 영상 다운로드 → 프레임 추출 → 3D 복원 → 웹 3D 뷰어
             (yt-dlp)       (ffmpeg)     (COLMAP/3DGS)  (Three.js)
```

## 설치 및 실행

> 기술 스택 확정 후 업데이트 예정

## 업무 스킴

이 프로젝트는 [TeamWork](https://github.com/conaonda/TeamWork) 업무 스킴을 따릅니다.
스프린트 자동화 실행:
```bash
cd /path/to/TeamWork
./scripts/sprint.sh --repo conaonda/EXTube --sprints 3
```

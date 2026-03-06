export interface SampleItem {
  id: string
  title: string
  description: string
  thumbnail: string
  type: 'ply' | 'potree' | 'splat'
  dataUrl: string
}

const SAMPLE_BASE = '/samples'

export const sampleItems: SampleItem[] = [
  {
    id: 'sample-temple',
    title: 'Temple of Heaven',
    description: '베이징 천단공원의 3D 복원 결과',
    thumbnail: `${SAMPLE_BASE}/temple/thumbnail.jpg`,
    type: 'splat',
    dataUrl: `${SAMPLE_BASE}/temple/point_cloud.splat`,
  },
  {
    id: 'sample-street',
    title: 'Seoul Street View',
    description: '서울 거리 풍경의 포인트 클라우드',
    thumbnail: `${SAMPLE_BASE}/street/thumbnail.jpg`,
    type: 'ply',
    dataUrl: `${SAMPLE_BASE}/street/point_cloud.ply`,
  },
  {
    id: 'sample-garden',
    title: 'Japanese Garden',
    description: '일본 정원의 Gaussian Splatting 복원',
    thumbnail: `${SAMPLE_BASE}/garden/thumbnail.jpg`,
    type: 'splat',
    dataUrl: `${SAMPLE_BASE}/garden/point_cloud.splat`,
  },
]

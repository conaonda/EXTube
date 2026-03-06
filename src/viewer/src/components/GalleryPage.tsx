import { useState } from 'react'
import { sampleItems } from '../sampleGallery'
import type { SampleItem } from '../sampleGallery'
import ViewerCanvas from './ViewerCanvas'
import '../Gallery.css'

export default function GalleryPage() {
  const [selected, setSelected] = useState<SampleItem | null>(null)

  if (selected) {
    const plyUrl = selected.type === 'ply' ? selected.dataUrl : null
    const potreeUrl = selected.type === 'potree' ? selected.dataUrl : null
    const splatUrl = selected.type === 'splat' ? selected.dataUrl : null

    return (
      <div className="gallery-viewer">
        <div className="gallery-viewer-header">
          <button className="gallery-back-btn" onClick={() => setSelected(null)}>
            &larr; 갤러리로 돌아가기
          </button>
          <span className="gallery-viewer-title">{selected.title}</span>
          <span className="gallery-viewer-badge">{selected.type.toUpperCase()}</span>
        </div>
        <div className="gallery-viewer-canvas">
          <ViewerCanvas plyUrl={plyUrl} potreeUrl={potreeUrl} splatUrl={splatUrl} />
        </div>
      </div>
    )
  }

  return (
    <div className="gallery">
      <div className="gallery-header">
        <h2 className="gallery-title">Sample Gallery</h2>
        <p className="gallery-subtitle">
          사전 복원된 3D 결과물을 탐색해 보세요. GPU 없이도 EXTube의 복원 품질을 확인할 수 있습니다.
        </p>
      </div>
      <div className="gallery-grid">
        {sampleItems.map((item) => (
          <button
            key={item.id}
            className="gallery-card"
            onClick={() => setSelected(item)}
            aria-label={`${item.title} 샘플 보기`}
          >
            <div className="gallery-card-thumbnail">
              <span className="gallery-card-placeholder">3D</span>
              <img
                src={item.thumbnail}
                alt={item.title}
                loading="lazy"
                onError={(e) => {
                  e.currentTarget.style.display = 'none'
                }}
              />
            </div>
            <div className="gallery-card-body">
              <h3 className="gallery-card-title">{item.title}</h3>
              <p className="gallery-card-desc">{item.description}</p>
              <span className="gallery-card-badge">{item.type.toUpperCase()}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

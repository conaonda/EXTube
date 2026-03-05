interface ViewerControlsProps {
  pointSize: number
  onPointSizeChange: (size: number) => void
  bgColor: string
  onBgColorChange: (color: string) => void
  showBoundingBox: boolean
  onToggleBoundingBox: () => void
  onResetCamera: () => void
  pointCount: number | null
  isPotree?: boolean
}

const BG_COLORS = [
  { label: '검정', value: '#000000' },
  { label: '그레이', value: '#808080' },
  { label: '흰색', value: '#ffffff' },
]

export default function ViewerControls({
  pointSize,
  onPointSizeChange,
  bgColor,
  onBgColorChange,
  showBoundingBox,
  onToggleBoundingBox,
  onResetCamera,
  pointCount,
  isPotree = false,
}: ViewerControlsProps) {
  return (
    <div
      className="viewer-controls"
      role="toolbar"
      aria-label="3D 뷰어 컨트롤"
    >
      <div>
        <label>
          포인트 크기: {pointSize.toFixed(3)}
          <input
            type="range"
            min="0.001"
            max="0.2"
            step="0.001"
            value={pointSize}
            onChange={(e) => onPointSizeChange(Number(e.target.value))}
            className="viewer-controls-range"
            aria-label="포인트 크기 조절"
          />
        </label>
      </div>

      <div className="viewer-controls-row">
        {BG_COLORS.map((c) => (
          <button
            key={c.value}
            onClick={() => onBgColorChange(c.value)}
            className={`viewer-controls-bg-btn ${bgColor === c.value ? 'viewer-controls-bg-btn--active' : ''}`}
            style={{
              background: c.value,
              color: c.value === '#000000' ? '#fff' : '#000',
            }}
            aria-label={`배경색 ${c.label}`}
            aria-pressed={bgColor === c.value}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div className="viewer-controls-row">
        <button
          onClick={onResetCamera}
          className="viewer-controls-btn"
          aria-label="카메라 위치 초기화"
        >
          카메라 리셋
        </button>
        <button
          onClick={onToggleBoundingBox}
          className={`viewer-controls-btn ${showBoundingBox ? 'viewer-controls-btn--active' : ''}`}
          aria-label="바운딩 박스 표시 토글"
          aria-pressed={showBoundingBox}
        >
          바운딩 박스
        </button>
      </div>

      {pointCount !== null && (
        <div className="viewer-controls-info" aria-label="포인트 수 정보">
          포인트 수: {pointCount.toLocaleString()}
          {isPotree && ' (LoD)'}
        </div>
      )}
    </div>
  )
}

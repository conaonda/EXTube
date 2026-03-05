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
      style={{
        position: 'absolute',
        bottom: '1rem',
        right: '1rem',
        zIndex: 10,
        background: 'rgba(255,255,255,0.9)',
        borderRadius: '8px',
        padding: '0.75rem',
        fontSize: '0.8rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
        minWidth: '180px',
      }}
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
            style={{ width: '100%' }}
          />
        </label>
      </div>

      <div style={{ display: 'flex', gap: '0.25rem' }}>
        {BG_COLORS.map((c) => (
          <button
            key={c.value}
            onClick={() => onBgColorChange(c.value)}
            style={{
              flex: 1,
              padding: '0.25rem',
              border:
                bgColor === c.value ? '2px solid #2563eb' : '1px solid #ccc',
              borderRadius: '4px',
              background: c.value,
              color: c.value === '#000000' ? '#fff' : '#000',
              cursor: 'pointer',
              fontSize: '0.7rem',
            }}
          >
            {c.label}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '0.25rem' }}>
        <button
          onClick={onResetCamera}
          style={{
            flex: 1,
            padding: '0.25rem 0.5rem',
            border: '1px solid #ccc',
            borderRadius: '4px',
            background: '#f3f4f6',
            cursor: 'pointer',
            fontSize: '0.75rem',
          }}
        >
          카메라 리셋
        </button>
        <button
          onClick={onToggleBoundingBox}
          style={{
            flex: 1,
            padding: '0.25rem 0.5rem',
            border: showBoundingBox
              ? '2px solid #2563eb'
              : '1px solid #ccc',
            borderRadius: '4px',
            background: showBoundingBox ? '#dbeafe' : '#f3f4f6',
            cursor: 'pointer',
            fontSize: '0.75rem',
          }}
        >
          바운딩 박스
        </button>
      </div>

      {pointCount !== null && (
        <div style={{ color: '#666', fontSize: '0.75rem' }}>
          포인트 수: {pointCount.toLocaleString()}
          {isPotree && ' (LoD)'}
        </div>
      )}
    </div>
  )
}

import { useState } from 'react'

interface JobFormProps {
  onSubmit: (url: string) => void
  disabled: boolean
}

export default function JobForm({ onSubmit, disabled }: JobFormProps) {
  const [url, setUrl] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (url.trim()) {
      onSubmit(url.trim())
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="YouTube URL을 입력하세요"
        disabled={disabled}
        style={{
          flex: 1,
          padding: '0.5rem 0.75rem',
          border: '1px solid #ccc',
          borderRadius: '4px',
          fontSize: '0.875rem',
        }}
      />
      <button
        type="submit"
        disabled={disabled || !url.trim()}
        style={{
          padding: '0.5rem 1rem',
          background: disabled ? '#999' : '#2563eb',
          color: '#fff',
          border: 'none',
          borderRadius: '4px',
          cursor: disabled ? 'not-allowed' : 'pointer',
          fontSize: '0.875rem',
        }}
      >
        3D 복원
      </button>
    </form>
  )
}

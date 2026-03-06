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
    <form onSubmit={handleSubmit} className="job-form" role="search" aria-label="YouTube URL 입력">
      <input
        type="text"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="YouTube URL을 입력하세요"
        disabled={disabled}
        className="job-form-input"
        aria-label="YouTube URL"
      />
      <button
        type="submit"
        disabled={disabled || !url.trim()}
        className="job-form-button"
        aria-label="3D 복원 시작"
        data-testid="job-submit"
      >
        3D 복원
      </button>
    </form>
  )
}

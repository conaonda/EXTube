import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import JobForm from '../JobForm'

describe('JobForm', () => {
  it('renders input and submit button', () => {
    render(<JobForm onSubmit={vi.fn()} disabled={false} />)
    expect(screen.getByPlaceholderText('YouTube URL을 입력하세요')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '3D 복원' })).toBeInTheDocument()
  })

  it('submit button is disabled when input is empty', () => {
    render(<JobForm onSubmit={vi.fn()} disabled={false} />)
    expect(screen.getByRole('button', { name: '3D 복원' })).toBeDisabled()
  })

  it('submit button is disabled when disabled prop is true', async () => {
    render(<JobForm onSubmit={vi.fn()} disabled={true} />)
    expect(screen.getByPlaceholderText('YouTube URL을 입력하세요')).toBeDisabled()
    expect(screen.getByRole('button', { name: '3D 복원' })).toBeDisabled()
  })

  it('enables submit button when URL is entered', async () => {
    const user = userEvent.setup()
    render(<JobForm onSubmit={vi.fn()} disabled={false} />)

    await user.type(screen.getByPlaceholderText('YouTube URL을 입력하세요'), 'https://youtube.com/watch?v=test')
    expect(screen.getByRole('button', { name: '3D 복원' })).toBeEnabled()
  })

  it('calls onSubmit with trimmed URL on form submission', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<JobForm onSubmit={onSubmit} disabled={false} />)

    await user.type(screen.getByPlaceholderText('YouTube URL을 입력하세요'), '  https://youtube.com/watch?v=test  ')
    await user.click(screen.getByRole('button', { name: '3D 복원' }))

    expect(onSubmit).toHaveBeenCalledWith('https://youtube.com/watch?v=test')
  })

  it('does not call onSubmit when URL is only whitespace', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<JobForm onSubmit={onSubmit} disabled={false} />)

    await user.type(screen.getByPlaceholderText('YouTube URL을 입력하세요'), '   ')
    // Button should still be disabled since trim() is empty
    expect(screen.getByRole('button', { name: '3D 복원' })).toBeDisabled()
  })
})

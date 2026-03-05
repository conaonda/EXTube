import { describe, expect, it } from 'vitest'
import { ApiError } from './api'

describe('ApiError', () => {
  it('sets name to ApiError', () => {
    const err = new ApiError('msg', 'network')
    expect(err.name).toBe('ApiError')
    expect(err.message).toBe('msg')
  })

  it('marks network errors as retryable', () => {
    expect(new ApiError('', 'network').retryable).toBe(true)
  })

  it('marks rate_limit errors as retryable', () => {
    expect(new ApiError('', 'rate_limit').retryable).toBe(true)
  })

  it('marks server errors as retryable', () => {
    expect(new ApiError('', 'server').retryable).toBe(true)
  })

  it('marks auth errors as NOT retryable', () => {
    expect(new ApiError('', 'auth').retryable).toBe(false)
  })

  it('marks client errors as NOT retryable', () => {
    expect(new ApiError('', 'client').retryable).toBe(false)
  })

  it('stores status code', () => {
    const err = new ApiError('', 'server', 503)
    expect(err.status).toBe(503)
  })

  it('defaults status to null', () => {
    const err = new ApiError('', 'network')
    expect(err.status).toBeNull()
  })

  it('is instance of Error', () => {
    expect(new ApiError('', 'client')).toBeInstanceOf(Error)
  })
})

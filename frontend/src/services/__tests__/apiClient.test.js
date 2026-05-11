import { describe, it, expect, vi, beforeEach } from 'vitest'
import api, { ApiError } from '../../services/apiClient'

/**
 * apiClient tests — #270
 *
 * NOTE: apiClient has retry logic for transient failures (429, 500, 502, 503, 504)
 * and network TypeErrors. Tests that don't specifically test retry behavior use
 * non-retryable status codes to avoid backoff delays.
 */

describe('apiClient', () => {
  beforeEach(() => {
    fetch.mockReset()
    localStorage.clear()
  })

  // ── GET requests ──

  it('GET returns parsed JSON on success', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ data: 'test' }),
    })

    const result = await api.get('/health')
    expect(result.data).toBe('test')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/health'),
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('GET throws ApiError on HTTP error', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ detail: 'Not found' }),
    })

    await expect(api.get('/missing')).rejects.toThrow(ApiError)
  })

  it('GET handles 404 status correctly', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ detail: 'Session not found' }),
    })

    try {
      await api.get('/diagrams/expired/questions')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect(err.status).toBe(404)
      // 404 has a user-friendly message; rawMessage preserves the API detail
      expect(err.rawMessage).toBe('Session not found')
    }
  })

  // ── POST requests ──

  it('POST sends JSON body with correct content-type', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ status: 'ok' }),
    })

    await api.post('/diagrams/d1/restore-session', { analysis: {} })

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/diagrams/d1/restore-session'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ analysis: {} }),
        headers: expect.objectContaining({ 'X-CSRF-Token': expect.any(String) }),
      }),
    )
  })

  it('unsafe internal requests include a matching CSRF header and Strict SameSite cookie', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.post('/diagrams/d1/analyze', { target: 'azure' })

    const callArgs = fetch.mock.calls[0]
    const token = callArgs[1].headers['X-CSRF-Token']
    expect(token).toEqual(expect.any(String))
    expect(document.cookie).toContain(`archmorph_csrf=${token}`)
  })

  it('POST with FormData does not set Content-Type header', async () => {
    const formData = new FormData()
    formData.append('file', new Blob(['test']), 'test.png')

    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ diagram_id: 'd1' }),
    })

    await api.post('/diagrams/upload', formData)

    const callArgs = fetch.mock.calls[0]
    // FormData should be sent as body, not stringified
    expect(callArgs[1].body).toBeInstanceOf(FormData)
  })

  // ── 204 No Content ──

  it('handles 204 No Content response', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({}),
    })

    const result = await api.delete('/some-resource')
    expect(result).toBeNull()
  })

  // ── Non-JSON responses (binary exports) ──

  it('returns raw response for non-JSON content types', async () => {
    const mockResponse = {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/octet-stream' }),
      blob: () => Promise.resolve(new Blob(['file-content'])),
    }
    fetch.mockResolvedValueOnce(mockResponse)

    const result = await api.get('/diagrams/d1/export')
    // Should return raw response, not parsed JSON
    expect(result.headers.get('content-type')).toBe('application/octet-stream')
  })

  it('throws ApiError for non-JSON error responses', async () => {
    // Use 400 (non-retryable) to avoid retry backoff delays
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      headers: new Headers({ 'content-type': 'text/plain' }),
    })

    await expect(api.get('/broken')).rejects.toThrow(ApiError)
  })

  // ── Error structure ──

  it('ApiError includes status and body', async () => {
    // Use 400 (non-retryable, no user-friendly mapping) so rawMessage is used as-is
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () =>
        Promise.resolve({
          error: {
            message: 'Rate limit exceeded',
            correlation_id: 'abc-123',
          },
        }),
    })

    try {
      await api.get('/diagrams/d1/analyze')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect(err.status).toBe(400)
      expect(err.message).toContain('Rate limit')
      expect(err.correlationId).toBe('abc-123')
    }
  })

  it('ApiError falls back to detail field', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ detail: 'Invalid request' }),
    })

    try {
      await api.get('/bad-request')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err.message).toContain('Invalid request')
    }
  })

  it('ApiError falls back to HTTP status when no message', async () => {
    // Use 422 (non-retryable, no user-friendly mapping) so fallback to "HTTP 422"
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({}),
    })

    try {
      await api.get('/unavailable')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err.message).toContain('422')
    }
  })

  // ── AbortSignal support ──

  it('passes abort signal to fetch via timeout controller', async () => {
    const controller = new AbortController()
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.get('/health', controller.signal)
    // apiClient wraps caller signals in a timeout controller — verify an AbortSignal is used
    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('pre-aborted signal throws AbortError without calling fetch', async () => {
    const controller = new AbortController()
    controller.abort()

    // apiClient detects pre-aborted signal and throws before calling fetch
    await expect(api.get('/health', controller.signal)).rejects.toThrow('The operation was aborted.')
    expect(fetch).not.toHaveBeenCalled()
  })

  // ── Network errors ──

  it('wraps network TypeError as ApiError after retries exhausted', async () => {
    // TypeError triggers retry (4 total attempts); after exhaustion wraps as ApiError
    for (let i = 0; i < 4; i++) {
      fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    }

    try {
      await api.get('/health')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect(err.status).toBe(0)
    }
  }, 30_000)

  // ── Auth requests ──

  it('auth method includes Authorization header', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.auth('GET', '/admin/metrics', { token: 'my-jwt-token' })

    const callArgs = fetch.mock.calls[0]
    expect(callArgs[1].headers.Authorization).toBe('Bearer my-jwt-token')
  })

  it('default methods include stored session token and SWA credentials', async () => {
    localStorage.setItem('archmorph_session_token', 'stored-jwt-token')

    const response = {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    }
    fetch
      .mockResolvedValueOnce(response)
      .mockResolvedValueOnce(response)
      .mockResolvedValueOnce(response)
      .mockResolvedValueOnce(response)

    await api.get('/diagrams/d1')
    await api.post('/diagrams/d1/analyze', { target: 'azure' })
    await api.patch('/diagrams/d1', { title: 'New title' })
    await api.delete('/diagrams/d1')

    for (const [, options] of fetch.mock.calls) {
      expect(options.credentials).toBe('include')
      expect(options.headers.Authorization).toBe('Bearer stored-jwt-token')
    }
  })

  it('does not overwrite caller-provided Authorization header', async () => {
    localStorage.setItem('archmorph_session_token', 'stored-jwt-token')

    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.auth('GET', '/admin/metrics', { token: 'explicit-token' })

    const callArgs = fetch.mock.calls[0]
    expect(callArgs[1].credentials).toBe('include')
    expect(callArgs[1].headers.Authorization).toBe('Bearer explicit-token')
  })

  it('does not attach default auth or credentials to third-party absolute URLs', async () => {
    localStorage.setItem('archmorph_session_token', 'stored-jwt-token')

    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.get('https://example.com/external.json')

    const callArgs = fetch.mock.calls[0]
    expect(callArgs[1].credentials).toBeUndefined()
    expect(callArgs[1].headers.Authorization).toBeUndefined()
    expect(callArgs[1].headers['X-CSRF-Token']).toBeUndefined()
  })

  // ── Session expiry detection ──

  it('404 on diagram endpoint indicates session expiry', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () =>
        Promise.resolve({
          detail: 'No analysis found for diagram expired-123. Upload and analyze first.',
        }),
    })

    try {
      await api.get('/diagrams/expired-123/questions')
    } catch (err) {
      expect(err.status).toBe(404)
      // This is the signal the frontend uses to trigger restore
    }
  })

  // ── PATCH requests ──

  it('PATCH sends JSON body', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ updated: true }),
    })

    await api.patch('/resource/1', { name: 'new-name' })

    const callArgs = fetch.mock.calls[0]
    expect(callArgs[1].method).toBe('PATCH')
    expect(callArgs[1].body).toBe(JSON.stringify({ name: 'new-name' }))
  })

  // ── Concurrent requests ──

  it('handles concurrent requests independently', async () => {
    fetch
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({ endpoint: 'health' }),
      })
      // Use 400 (non-retryable) to avoid retry delays in concurrent test
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({ detail: 'Bad request' }),
      })

    const [healthResult, errorResult] = await Promise.allSettled([
      api.get('/health'),
      api.get('/broken'),
    ])

    expect(healthResult.status).toBe('fulfilled')
    expect(healthResult.value.endpoint).toBe('health')
    expect(errorResult.status).toBe('rejected')
    expect(errorResult.reason.status).toBe(400)
  })
})

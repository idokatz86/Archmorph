import { describe, it, expect, vi, beforeEach } from 'vitest'
import api, { ApiError } from '../../services/apiClient'

describe('apiClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

    try {
      await api.get('/missing')
    } catch (err) {
      // Catch the second call that will also throw
    }
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
      expect(err.message).toContain('Session not found')
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
      }),
    )
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
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      headers: new Headers({ 'content-type': 'text/plain' }),
    })

    await expect(api.get('/broken')).rejects.toThrow(ApiError)
  })

  // ── Error structure ──

  it('ApiError includes status and body', async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 429,
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
      expect(err.status).toBe(429)
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
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({}),
    })

    try {
      await api.get('/unavailable')
      expect.fail('Should have thrown')
    } catch (err) {
      expect(err.message).toContain('503')
    }
  })

  // ── AbortSignal support ──

  it('passes abort signal to fetch', async () => {
    const controller = new AbortController()
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ ok: true }),
    })

    await api.get('/health', controller.signal)
    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ signal: controller.signal }),
    )
  })

  it('abort signal triggers AbortError', async () => {
    const controller = new AbortController()
    controller.abort()

    fetch.mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'))

    await expect(api.get('/health', controller.signal)).rejects.toThrow('Aborted')
  })

  // ── Network errors ──

  it('propagates network errors', async () => {
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(api.get('/health')).rejects.toThrow('Failed to fetch')
  })

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
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({ detail: 'Server error' }),
      })

    const [healthResult, errorResult] = await Promise.allSettled([
      api.get('/health'),
      api.get('/broken'),
    ])

    expect(healthResult.status).toBe('fulfilled')
    expect(healthResult.value.endpoint).toBe('health')
    expect(errorResult.status).toBe('rejected')
    expect(errorResult.reason.status).toBe(500)
  })
})

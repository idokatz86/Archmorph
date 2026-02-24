import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import MonitoringDashboard from '../MonitoringDashboard'

describe('MonitoringDashboard', () => {
  const mockMonData = {
    overview: {
      total_requests: 1500,
      total_errors: 5,
      error_rate_pct: 0.3,
      uptime: '12h 30m',
      memory_mb: 256,
      cpu_percent: 15,
    },
    latency: {
      avg_ms: 150,
      p50_ms: 100,
      p95_ms: 300,
      p99_ms: 500,
      max_ms: 800,
      total_samples: 1500,
    },
    status_codes: { '404': 3, '500': 2 },
    top_endpoints: [
      { endpoint: '/api/services', requests: 500, errors: 1, avg_ms: 50, p95_ms: 120 },
      { endpoint: '/api/chat', requests: 200, errors: 0, avg_ms: 200, p95_ms: 400 },
    ],
  }
  const mockHealth = { status: 'healthy', version: '3.0.0' }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockMonData) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHealth) })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows loading spinner initially', () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders monitoring title after loading', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('Application Monitoring')).toBeInTheDocument()
  })

  it('shows health status badge', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    const healthyElements = await screen.findAllByText('Healthy')
    expect(healthyElements.length).toBeGreaterThan(0)
  })

  it('displays total requests', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('1.5K')).toBeInTheDocument()
  })

  it('displays error rate', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('0.3%')).toBeInTheDocument()
  })

  it('displays uptime', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('12h 30m')).toBeInTheDocument()
  })

  it('shows latency distribution section', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('Latency Distribution')).toBeInTheDocument()
  })

  it('shows endpoint performance section', async () => {
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('Endpoint Performance')).toBeInTheDocument()
  })

  it('displays error on API failure', async () => {
    fetch.mockReset()
    fetch
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHealth) })
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('Monitoring Unavailable')).toBeInTheDocument()
  })

  it('shows retry button on error', async () => {
    fetch.mockReset()
    fetch
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHealth) })
    render(<MonitoringDashboard sessionToken="tok" />)
    expect(await screen.findByText('Retry')).toBeInTheDocument()
  })

  it('does not fetch when sessionToken is missing', () => {
    fetch.mockReset()
    render(<MonitoringDashboard sessionToken={null} />)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('calls onAuthError on 401 response', async () => {
    fetch.mockReset()
    const onAuthError = vi.fn()
    fetch
      .mockResolvedValueOnce({ ok: false, status: 401 })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockHealth) })
    render(<MonitoringDashboard sessionToken="tok" onAuthError={onAuthError} />)
    await waitFor(() => expect(onAuthError).toHaveBeenCalled())
  })
})

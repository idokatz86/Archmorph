import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDashboard from '../AdminDashboard'

describe('AdminDashboard', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({ ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }),
      ok: true,
      status: 200,
      json: () => Promise.resolve({ token: 'test-token' }),
    })
  })

  it('renders login screen by default', () => {
    render(<AdminDashboard onClose={mockOnClose} />)
    expect(screen.getByText('Admin Login')).toBeInTheDocument()
  })

  it('shows admin key input field', () => {
    render(<AdminDashboard onClose={mockOnClose} />)
    expect(screen.getByPlaceholderText('Admin key')).toBeInTheDocument()
  })

  it('has a close button on login screen', () => {
    render(<AdminDashboard onClose={mockOnClose} />)
    expect(screen.getByText('Close')).toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    await user.click(screen.getByText('Close'))
    expect(mockOnClose).toHaveBeenCalledTimes(1)
  })

  it('shows Sign In button disabled when key is empty', () => {
    render(<AdminDashboard onClose={mockOnClose} />)
    const submitBtn = screen.getByText('Sign In')
    expect(submitBtn.closest('button')).toBeDisabled()
  })

  it('enables Sign In button when key is entered', async () => {
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'secret' } })
    const submitBtn = screen.getByText('Sign In')
    await waitFor(() => expect(submitBtn.closest('button')).not.toBeDisabled())
  })

  it('shows error on invalid admin key', async () => {
    fetch.mockResolvedValue({ ok: false, status: 401, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: { message: 'Invalid admin key' } }) })
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'wrong' } })
    const submitBtn = screen.getByText('Sign In').closest('button')
    await waitFor(() => expect(submitBtn).not.toBeDisabled())
    await user.click(submitBtn)
    expect(await screen.findByText('Invalid admin key')).toBeInTheDocument()
  })

  it('shows error when server is down', async () => {
    fetch.mockRejectedValue(new TypeError('Connection error'))
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'key' } })
    await user.click(screen.getByText('Sign In'))
    expect(await screen.findByText('Network error — check your connection.')).toBeInTheDocument()
  })

  it('shows 503 error when admin not configured', async () => {
    fetch.mockResolvedValue({ ok: false, status: 503, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: 'Admin API not configured on server' }) })
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'key' } })
    await user.click(screen.getByText('Sign In'))
    expect(await screen.findByText('Admin API not configured on server', {}, { timeout: 8000 })).toBeInTheDocument()
  })

  it('navigates to dashboard after successful login', async () => {
    // Login response
    fetch.mockResolvedValueOnce({ ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }),
      ok: true,
      status: 200,
      json: () => Promise.resolve({ token: 'test-token' }),
    })
    // Dashboard data fetches (funnel, metrics, daily, recent, costs)
    const dashboardResponse = { ok: true, json: () => Promise.resolve({ funnel: [], total_sessions: 0, completion_rate: 0 }) }
    fetch.mockResolvedValue({ ...dashboardResponse, ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }) })

    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'valid-key' } })
    await user.click(screen.getByText('Sign In'))

    await waitFor(() => {
      expect(screen.queryByText('Admin Login')).not.toBeInTheDocument()
    })
  })

  it('renders Day-7 retention tile after login', async () => {
    // URL-aware mock that returns retention payload only for the retention endpoint.
    const retentionPayload = {
      enabled: true,
      lookback_days: 30,
      total_cohort: 200,
      total_returned: 80,
      overall_day7_return_rate: 0.40,
      kpi_target: 0.35,
      trend: [
        { cohort_day: '2025-01-01', cohort_size: 50, returned_day7_count: 22, return_rate: 0.44 },
        { cohort_day: '2025-01-02', cohort_size: 45, returned_day7_count: 18, return_rate: 0.40 },
      ],
    }
    fetch.mockImplementation((url) => {
      const u = String(url)
      if (u.includes('/admin/login')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve({ token: 'test-token' }),
        })
      }
      if (u.includes('/admin/retention/baseline')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve(retentionPayload),
        })
      }
      return Promise.resolve({
        ok: true, status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({}),
      })
    })

    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'valid-key' } })
    await user.click(screen.getByText('Sign In'))

    const tile = await screen.findByTestId('retention-tile', {}, { timeout: 8000 })
    expect(tile).toBeInTheDocument()
    expect(tile).toHaveTextContent('Day-7 Return Rate')
    expect(tile).toHaveTextContent('40.0%')
    expect(tile).toHaveTextContent('On target')
    expect(tile).toHaveTextContent('Cohort total')
    expect(tile).toHaveTextContent('200')
    expect(tile).toHaveTextContent('Returned')
    expect(tile).toHaveTextContent('80')
  })

  it('marks retention tile below KPI when rate is under target', async () => {
    const retentionPayload = {
      enabled: true,
      lookback_days: 30,
      total_cohort: 100,
      total_returned: 12,
      overall_day7_return_rate: 0.12,
      kpi_target: 0.35,
      trend: [],
    }
    fetch.mockImplementation((url) => {
      const u = String(url)
      if (u.includes('/admin/login')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve({ token: 'test-token' }),
        })
      }
      if (u.includes('/admin/retention/baseline')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve(retentionPayload),
        })
      }
      return Promise.resolve({
        ok: true, status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({}),
      })
    })

    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'valid-key' } })
    await user.click(screen.getByText('Sign In'))

    const tile = await screen.findByTestId('retention-tile', {}, { timeout: 8000 })
    expect(tile).toHaveTextContent('12.0%')
    expect(tile).toHaveTextContent('−23.0 pp')
    expect(tile).not.toHaveTextContent('On target')
  })

  it('shows disabled banner when retention tracking is off', async () => {
    const retentionPayload = {
      enabled: false,
      lookback_days: 30,
      total_cohort: 0,
      total_returned: 0,
      overall_day7_return_rate: 0,
      kpi_target: 0.35,
      trend: [],
    }
    fetch.mockImplementation((url) => {
      const u = String(url)
      if (u.includes('/admin/login')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve({ token: 'test-token' }),
        })
      }
      if (u.includes('/admin/retention/baseline')) {
        return Promise.resolve({
          ok: true, status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: () => Promise.resolve(retentionPayload),
        })
      }
      return Promise.resolve({
        ok: true, status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.resolve({}),
      })
    })

    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    fireEvent.change(screen.getByPlaceholderText('Admin key'), { target: { value: 'valid-key' } })
    await user.click(screen.getByText('Sign In'))

    const tile = await screen.findByTestId('retention-tile', {}, { timeout: 8000 })
    expect(tile).toHaveTextContent('Disabled')
    expect(tile).toHaveTextContent('RETENTION_TRACKING_ENABLED=true')
  })
})

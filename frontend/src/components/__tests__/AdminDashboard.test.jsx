import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdminDashboard from '../AdminDashboard'

describe('AdminDashboard', () => {
  const mockOnClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({
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
    await user.type(screen.getByPlaceholderText('Admin key'), 'secret')
    const submitBtn = screen.getByText('Sign In')
    expect(submitBtn.closest('button')).not.toBeDisabled()
  })

  it('shows error on invalid admin key', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 401, json: () => Promise.resolve({}) })
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    await user.type(screen.getByPlaceholderText('Admin key'), 'wrong')
    await user.click(screen.getByText('Sign In'))
    expect(await screen.findByText('Invalid admin key')).toBeInTheDocument()
  })

  it('shows error when server is down', async () => {
    fetch.mockRejectedValueOnce(new Error('Connection error'))
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    await user.type(screen.getByPlaceholderText('Admin key'), 'key')
    await user.click(screen.getByText('Sign In'))
    expect(await screen.findByText('Unable to reach server')).toBeInTheDocument()
  })

  it('shows 503 error when admin not configured', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 503, json: () => Promise.resolve({}) })
    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    await user.type(screen.getByPlaceholderText('Admin key'), 'key')
    await user.click(screen.getByText('Sign In'))
    expect(await screen.findByText('Admin API not configured on server')).toBeInTheDocument()
  })

  it('navigates to dashboard after successful login', async () => {
    // Login response
    fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ token: 'test-token' }),
    })
    // Dashboard data fetches (funnel, metrics, daily, recent, costs)
    const dashboardResponse = { ok: true, json: () => Promise.resolve({ funnel: [], total_sessions: 0, completion_rate: 0 }) }
    fetch.mockResolvedValue(dashboardResponse)

    const user = userEvent.setup()
    render(<AdminDashboard onClose={mockOnClose} />)
    await user.type(screen.getByPlaceholderText('Admin key'), 'valid-key')
    await user.click(screen.getByText('Sign In'))

    await waitFor(() => {
      expect(screen.queryByText('Admin Login')).not.toBeInTheDocument()
    })
  })
})

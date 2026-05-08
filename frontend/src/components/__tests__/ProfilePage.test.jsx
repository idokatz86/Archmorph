import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ProfilePage from '../Auth/ProfilePage'

const logout = vi.fn()

vi.mock('../Auth/AuthProvider', () => ({
  useAuth: () => ({
    user: { id: 'u1', name: 'Ada', email: 'ada@example.com', provider: 'github' },
    isAuthenticated: true,
    logout,
  }),
}))

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.body.style.overflow = ''
    fetch.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: () => Promise.resolve({ display_name: 'Ada' }),
    })
  })

  it('renders as an accessible dialog and closes on Escape', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()

    render(<ProfilePage isOpen onClose={onClose} />)

    expect(screen.getByRole('dialog', { name: 'Profile Settings' })).toBeInTheDocument()
    expect(document.body.style.overflow).toBe('hidden')

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('sends SWA credentials and stored token when loading profile', async () => {
    localStorage.setItem('archmorph_session_token', 'stored-token')

    render(<ProfilePage isOpen onClose={vi.fn()} />)

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const [, options] = fetch.mock.calls[0]
    expect(options.credentials).toBe('include')
    expect(options.headers.Authorization).toBe('Bearer stored-token')
  })

  it('sends SWA credentials when saving profile without localStorage token', async () => {
    const user = userEvent.setup()
    render(<ProfilePage isOpen onClose={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: /Save/ }))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    const [, options] = fetch.mock.calls[1]
    expect(options.method).toBe('PUT')
    expect(options.credentials).toBe('include')
    expect(options.headers.Authorization).toBeUndefined()
  })
})

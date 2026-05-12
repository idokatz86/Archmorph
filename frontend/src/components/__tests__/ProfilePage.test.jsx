import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
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

  it('closes on backdrop click and restores focus after unmount', async () => {
    const user = userEvent.setup()

    function Harness() {
      const [open, setOpen] = React.useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open profile</button>
          <ProfilePage isOpen={open} onClose={() => setOpen(false)} />
        </>
      )
    }

    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open profile' })
    trigger.focus()
    await user.click(trigger)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Close profile settings' })).toHaveFocus())
    await user.click(screen.getByTestId('profile-backdrop'))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Profile Settings' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('sends SWA credentials and stored token when loading profile', async () => {
    localStorage.setItem('archmorph_session_token', 'stored-token')

    render(<ProfilePage isOpen onClose={vi.fn()} />)

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const [, options] = fetch.mock.calls[0]
    expect(options.credentials).toBe('include')
    expect(options.headers.Authorization).toBe('Bearer stored-token')
  })

  it('programmatically labels every editable profile field', async () => {
    render(<ProfilePage isOpen onClose={vi.fn()} />)

    expect(screen.getByLabelText('Display Name')).toBeInTheDocument()
    expect(screen.getByLabelText('Company')).toBeInTheDocument()
    expect(screen.getByLabelText('Role')).toBeInTheDocument()
    expect(screen.getByLabelText('Source Cloud')).toBeInTheDocument()
    expect(screen.getByLabelText('IaC Format')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Display Name')).toHaveValue('Ada'))
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

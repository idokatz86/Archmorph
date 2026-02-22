import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatWidget from '../ChatWidget'

describe('ChatWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({
      json: () => Promise.resolve({ reply: 'Hello from AI', action: null, data: null }),
    })
  })

  it('renders the toggle button', () => {
    render(<ChatWidget />)
    expect(screen.getByLabelText('Open chat')).toBeInTheDocument()
  })

  it('opens chat panel when toggled', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    expect(screen.getByText('Archmorph AI Assistant')).toBeInTheDocument()
  })

  it('shows initial assistant message when opened', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    expect(screen.getByText(/I'm the Archmorph AI assistant/)).toBeInTheDocument()
  })

  it('closes chat panel when close button is clicked', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    expect(screen.getByText('Archmorph AI Assistant')).toBeInTheDocument()
    // There are two elements with 'Close chat' aria-label (toggle button + header X button)
    const closeButtons = screen.getAllByLabelText('Close chat')
    // Click the header X button (the smaller one inside the panel)
    await user.click(closeButtons[closeButtons.length - 1])
    expect(screen.queryByText('Archmorph AI Assistant')).not.toBeInTheDocument()
  })

  it('has a message input field when open', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    expect(screen.getByLabelText('Chat message')).toBeInTheDocument()
  })

  it('sends a message and shows it in chat', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    const input = screen.getByLabelText('Chat message')
    await user.type(input, 'Hello there')
    await user.keyboard('{Enter}')
    expect(screen.getByText('Hello there')).toBeInTheDocument()
  })

  it('shows the AI reply after sending a message', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    const input = screen.getByLabelText('Chat message')
    await user.type(input, 'Hi')
    await user.keyboard('{Enter}')
    expect(await screen.findByText('Hello from AI')).toBeInTheDocument()
  })

  it('shows error message on network failure', async () => {
    fetch.mockRejectedValueOnce(new Error('Network error'))
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    const input = screen.getByLabelText('Chat message')
    await user.type(input, 'test')
    await user.keyboard('{Enter}')
    expect(await screen.findByText(/couldn't connect/)).toBeInTheDocument()
  })

  it('does not send empty messages', async () => {
    const user = userEvent.setup()
    render(<ChatWidget />)
    await user.click(screen.getByLabelText('Open chat'))
    const input = screen.getByLabelText('Chat message')
    await user.click(input)
    await user.keyboard('{Enter}')
    // Only the initial message should exist, no fetch call
    expect(fetch).not.toHaveBeenCalled()
  })
})

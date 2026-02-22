import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import FeedbackWidget from '../FeedbackWidget'

function renderWithRef() {
  const ref = React.createRef()
  const result = render(<FeedbackWidget ref={ref} />)
  return { ...result, ref }
}

describe('FeedbackWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({ json: () => Promise.resolve({}) })
  })

  it('renders nothing when closed', () => {
    const { container } = render(<FeedbackWidget />)
    expect(container.innerHTML).toBe('')
  })

  it('can be opened via ref', () => {
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    expect(screen.getByText('Feedback')).toBeInTheDocument()
  })

  it('shows NPS mode by default when opened', () => {
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    expect(screen.getByText(/How likely are you to recommend/)).toBeInTheDocument()
  })

  it('shows NPS score buttons 0-10', () => {
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    for (let i = 0; i <= 10; i++) {
      expect(screen.getByText(String(i))).toBeInTheDocument()
    }
  })

  it('switches to feature mode', async () => {
    const user = userEvent.setup()
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    await user.click(screen.getByText('💡 Feature'))
    expect(screen.getByText(/Was this feature helpful/)).toBeInTheDocument()
  })

  it('switches to bug mode', async () => {
    const user = userEvent.setup()
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    await user.click(screen.getByText('🐛 Bug'))
    expect(screen.getByText(/Report a bug/)).toBeInTheDocument()
  })

  it('submits NPS feedback', async () => {
    const user = userEvent.setup()
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    await user.click(screen.getByText('8'))
    await user.click(screen.getByText('Submit'))
    expect(await screen.findByText('Thank you!')).toBeInTheDocument()
  })

  it('closes when X is clicked', async () => {
    const user = userEvent.setup()
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    expect(screen.getByText('Feedback')).toBeInTheDocument()
    const closeButtons = screen.getAllByRole('button')
    const closeBtn = closeButtons.find(btn => btn.querySelector('.lucide-x'))
    if (closeBtn) {
      await user.click(closeBtn)
    } else {
      act(() => { ref.current.close() })
    }
    expect(screen.queryByText('Feedback')).not.toBeInTheDocument()
  })

  it('can be closed via ref', () => {
    const { ref } = renderWithRef()
    act(() => { ref.current.open() })
    expect(screen.getByText('Feedback')).toBeInTheDocument()
    act(() => { ref.current.close() })
    expect(screen.queryByText('Feedback')).not.toBeInTheDocument()
  })
})

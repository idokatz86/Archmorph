import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'

vi.mock('../FeedbackWidget', () => {
  const { forwardRef, useImperativeHandle } = require('react')
  return {
    default: forwardRef(function MockFeedback(props, ref) {
      useImperativeHandle(ref, () => ({ open: vi.fn(), close: vi.fn() }))
      return null
    }),
  }
})

vi.mock('../Auth', () => ({
  UserMenu: () => <button type="button">User</button>,
}))

import Nav from '../Nav'

describe('Nav', () => {
  const defaultProps = {
    activeTab: 'translator',
    setActiveTab: vi.fn(),
    updateStatus: null,
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the Archmorph brand', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByRole('button', { name: 'Go to home' })).toBeInTheDocument()
    expect(screen.getByText('Arch')).toBeInTheDocument()
    expect(screen.getByText('morph')).toBeInTheDocument()
  })

  it('renders command and theme controls', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByRole('button', { name: 'Open command palette' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Switch to .* mode/ })).toBeInTheDocument()
  })

  it('renders navigation tabs', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByText('Workbench')).toBeInTheDocument()
    expect(screen.getByText('Reference')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /More/ })).toBeInTheDocument()
  })

  it('highlights the active tab', () => {
    render(<Nav {...defaultProps} activeTab="services" />)
    const servicesBtn = screen.getByText('Reference').closest('button')
    expect(servicesBtn).toHaveAttribute('aria-current', 'page')
  })

  it('calls setActiveTab when a tab is clicked', async () => {
    const user = userEvent.setup()
    render(<Nav {...defaultProps} />)
    await user.click(screen.getByText('Reference'))
    expect(defaultProps.setActiveTab).toHaveBeenCalledWith('services')
  })

  it('opens the more navigation menu', async () => {
    const user = userEvent.setup()
    render(<Nav {...defaultProps} />)
    await user.click(screen.getByRole('button', { name: /More/ }))
    expect(screen.getByText('Roadmap')).toBeInTheDocument()
    expect(screen.queryByText('Drift')).not.toBeInTheDocument()
  })

  it('shows catalog live status when scheduler is running', () => {
    render(<Nav {...defaultProps} updateStatus={{ scheduler_running: true }} />)
    expect(screen.getByRole('status', { name: /Catalog syncing/ })).toBeInTheDocument()
  })

  it('shows catalog idle status when scheduler is not running', () => {
    render(<Nav {...defaultProps} updateStatus={{ scheduler_running: false }} />)
    expect(screen.getByRole('status', { name: 'Catalog idle' })).toBeInTheDocument()
  })

  it('renders feedback button', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByRole('button', { name: 'Give feedback' })).toBeInTheDocument()
  })
})

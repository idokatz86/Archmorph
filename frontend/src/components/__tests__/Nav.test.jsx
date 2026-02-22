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
    expect(screen.getByText('Archmorph')).toBeInTheDocument()
  })

  it('renders Cloud Translator subtitle', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByText('Cloud Translator')).toBeInTheDocument()
  })

  it('renders navigation tabs', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByText('Translator')).toBeInTheDocument()
    expect(screen.getByText('Services')).toBeInTheDocument()
    expect(screen.getByText('Roadmap')).toBeInTheDocument()
  })

  it('highlights the active tab', () => {
    render(<Nav {...defaultProps} activeTab="services" />)
    const servicesBtn = screen.getByText('Services').closest('button')
    expect(servicesBtn).toHaveAttribute('aria-current', 'page')
  })

  it('calls setActiveTab when a tab is clicked', async () => {
    const user = userEvent.setup()
    render(<Nav {...defaultProps} />)
    await user.click(screen.getByText('Services'))
    expect(defaultProps.setActiveTab).toHaveBeenCalledWith('services')
  })

  it('shows version badge', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByText(/^v\d+\.\d+\.\d+$/)).toBeInTheDocument()
  })

  it('shows catalog live status when scheduler is running', () => {
    render(<Nav {...defaultProps} updateStatus={{ scheduler_running: true }} />)
    expect(screen.getByText('Catalog Live')).toBeInTheDocument()
  })

  it('shows catalog idle status when scheduler is not running', () => {
    render(<Nav {...defaultProps} updateStatus={{ scheduler_running: false }} />)
    expect(screen.getByText('Catalog Idle')).toBeInTheDocument()
  })

  it('renders feedback button', () => {
    render(<Nav {...defaultProps} />)
    expect(screen.getByTitle('Give Feedback')).toBeInTheDocument()
  })
})

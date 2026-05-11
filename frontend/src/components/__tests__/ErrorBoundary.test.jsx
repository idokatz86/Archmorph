import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ErrorBoundary from '../ErrorBoundary'
import { clearErrorReporter, setErrorReporter } from '../../services/errorReporter'

function ProblemChild() {
  throw new Error('Test error')
}

function GoodChild() {
  return <div>All good</div>
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearErrorReporter()
    // Suppress React error boundary console.error noise
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    clearErrorReporter()
  })

  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <GoodChild />
      </ErrorBoundary>
    )
    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  it('renders fallback UI when child throws', () => {
    const reporter = vi.fn()
    setErrorReporter(reporter)
    render(
      <ErrorBoundary>
        <ProblemChild />
      </ErrorBoundary>
    )
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(reporter).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({ context: 'ErrorBoundary' }),
    )
  })

  it('shows Try Again button on error', () => {
    render(
      <ErrorBoundary>
        <ProblemChild />
      </ErrorBoundary>
    )
    expect(screen.getByText('Try Again')).toBeInTheDocument()
  })

  it('shows helpful message on error', () => {
    render(
      <ErrorBoundary>
        <ProblemChild />
      </ErrorBoundary>
    )
    expect(screen.getByText(/unexpected error/)).toBeInTheDocument()
  })

  it('resets error state when Try Again is clicked', async () => {
    const user = userEvent.setup()
    // We need a component that can toggle between throwing and not
    let shouldThrow = true
    function ToggleChild() {
      if (shouldThrow) throw new Error('boom')
      return <div>Recovered</div>
    }

    const { rerender } = render(
      <ErrorBoundary>
        <ToggleChild />
      </ErrorBoundary>
    )
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()

    shouldThrow = false
    await user.click(screen.getByText('Try Again'))
    // After reset, ErrorBoundary tries to re-render children
    // Since shouldThrow is now false, it should show recovered content
    expect(screen.getByText('Recovered')).toBeInTheDocument()
  })
})

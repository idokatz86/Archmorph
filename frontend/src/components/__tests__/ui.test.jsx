import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Badge, Button, Card } from '../ui'

describe('Badge', () => {
  it('renders children text', () => {
    render(<Badge>Test</Badge>)
    expect(screen.getByText('Test')).toBeInTheDocument()
  })

  it('applies default variant styling', () => {
    const { container } = render(<Badge>Default</Badge>)
    expect(container.firstChild).toHaveClass('inline-flex')
  })

  it('renders with high variant', () => {
    render(<Badge variant="high">High</Badge>)
    expect(screen.getByText('High')).toBeInTheDocument()
  })

  it('renders with aws variant', () => {
    render(<Badge variant="aws">AWS</Badge>)
    expect(screen.getByText('AWS')).toBeInTheDocument()
  })

  it('renders with azure variant', () => {
    render(<Badge variant="azure">Azure</Badge>)
    expect(screen.getByText('Azure')).toBeInTheDocument()
  })
})

describe('Button', () => {
  it('renders children text', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByText('Click me')).toBeInTheDocument()
  })

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()
    render(<Button onClick={handleClick}>Click</Button>)
    await user.click(screen.getByText('Click'))
    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('is disabled when loading prop is true', () => {
    render(<Button loading>Loading</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('renders icon when provided', () => {
    const MockIcon = (props) => <svg data-testid="mock-icon" {...props} />
    render(<Button icon={MockIcon}>With Icon</Button>)
    expect(screen.getByTestId('mock-icon')).toBeInTheDocument()
  })

  it('applies secondary variant class', () => {
    const { container } = render(<Button variant="secondary">Secondary</Button>)
    expect(container.firstChild.className).toContain('bg-secondary')
  })

  it('applies ghost variant class', () => {
    const { container } = render(<Button variant="ghost">Ghost</Button>)
    expect(container.firstChild.className).toContain('hover:bg-secondary')
  })

  it('applies small size class', () => {
    const { container } = render(<Button size="sm">Small</Button>)
    expect(container.firstChild.className).toContain('px-3')
  })
})

describe('Card', () => {
  it('renders children', () => {
    render(<Card><p>Card content</p></Card>)
    expect(screen.getByText('Card content')).toBeInTheDocument()
  })

  it('applies hover styles when hover prop is true', () => {
    const { container } = render(<Card hover>Hoverable</Card>)
    expect(container.firstChild.className).toContain('hover:border-border-light')
  })

  it('applies custom className', () => {
    const { container } = render(<Card className="p-4">Styled</Card>)
    expect(container.firstChild.className).toContain('p-4')
  })

  it('does not have hover class without hover prop', () => {
    const { container } = render(<Card>Plain</Card>)
    expect(container.firstChild.className).not.toContain('cursor-pointer')
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import DiagramTranslator from '../../DiagramTranslator'

// Mock Prism to avoid require issues
vi.mock('prismjs', () => ({ default: { highlightAll: vi.fn() } }))

describe('DiagramTranslator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) })
  })

  it('renders without crashing', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText('Upload')).toBeInTheDocument()
  })

  it('shows the step progress bar', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText('Upload')).toBeInTheDocument()
    expect(screen.getByText('Analyzing')).toBeInTheDocument()
    expect(screen.getByText('Customize')).toBeInTheDocument()
  })

  it('shows upload step by default', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText('Upload Architecture Diagram')).toBeInTheDocument()
  })

  it('shows drag & drop zone', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText(/Drag & drop your AWS or GCP diagram/)).toBeInTheDocument()
  })

  it('shows sample diagrams section', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText(/try with a sample architecture/)).toBeInTheDocument()
  })

  it('shows supported file formats', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText(/Supports PNG, JPG, SVG, PDF/)).toBeInTheDocument()
  })

  it('shows sample buttons', () => {
    render(<DiagramTranslator />)
    expect(screen.getByText('AWS IaaS')).toBeInTheDocument()
    expect(screen.getByText('GCP IaaS')).toBeInTheDocument()
  })
})

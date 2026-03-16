import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import DiagramTranslator from '../../DiagramTranslator'

// Mock Prism to avoid require issues
vi.mock('prismjs', () => ({
  default: {
    highlightAll: vi.fn(),
    highlight: vi.fn((code) => code),
    languages: { hcl: {}, json: {} },
  },
}))
vi.mock('prismjs/components/prism-hcl', () => ({}))
vi.mock('prismjs/components/prism-json', () => ({}))

describe('DiagramTranslator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) })
  })

  it('renders without crashing', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText('Upload')).toBeInTheDocument()
  })

  it('shows the step progress bar', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText('Upload')).toBeInTheDocument()
    expect(await screen.findByText('Analyzing')).toBeInTheDocument()
    expect(await screen.findByText('Customize')).toBeInTheDocument()
  })

  it('shows upload step by default', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText('Upload Architecture Diagram')).toBeInTheDocument()
  })

  it('shows drag & drop zone', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText(/Drag & drop your AWS or GCP diagram/)).toBeInTheDocument()
  })

  it('shows sample diagrams section', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText(/try with a sample architecture/)).toBeInTheDocument()
  })

  it('shows supported file formats', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText(/Supports PNG, JPG, SVG, PDF/)).toBeInTheDocument()
  })

  it('shows sample buttons', async () => {
    render(<DiagramTranslator />)
    expect(await screen.findByText('Hub & Spoke')).toBeInTheDocument()
    expect(await screen.findByText('GKE Cluster')).toBeInTheDocument()
  })
})

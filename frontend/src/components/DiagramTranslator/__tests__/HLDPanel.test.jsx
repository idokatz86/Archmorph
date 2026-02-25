import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import HLDPanel from '../../DiagramTranslator/HLDPanel'

describe('HLDPanel', () => {
  const defaultProps = {
    hldData: null,
    hldTab: 'overview',
    hldExportLoading: {},
    hldIncludeDiagrams: true,
    copyFeedback: {},
    onSetHldTab: vi.fn(),
    onSetHldIncludeDiagrams: vi.fn(),
    onHldExport: vi.fn(),
    onCopyWithFeedback: vi.fn(),
  }

  it('renders nothing when hldData is null', () => {
    const { container } = render(<HLDPanel {...defaultProps} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders title when hldData is provided', () => {
    const hldData = {
      hld: { title: 'My Architecture HLD', executive_summary: 'Summary text' },
      markdown: '# HLD',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('My Architecture HLD')).toBeInTheDocument()
  })

  it('shows AI-generated subtitle', () => {
    const hldData = {
      hld: { title: 'HLD Doc' },
      markdown: '',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('AI-generated architecture document')).toBeInTheDocument()
  })

  it('shows tab navigation', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Services')).toBeInTheDocument()
    expect(screen.getByText('Networking')).toBeInTheDocument()
    expect(screen.getByText('Security')).toBeInTheDocument()
    expect(screen.getByText('Migration')).toBeInTheDocument()
    expect(screen.getByText('WAF')).toBeInTheDocument()
  })

  it('shows export document formats', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Word')).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('PowerPoint')).toBeInTheDocument()
  })

  it('shows overview tab content with executive summary', () => {
    const hldData = {
      hld: { title: 'HLD', executive_summary: 'This is the summary' },
      markdown: '',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} hldTab="overview" />)
    expect(screen.getByText('This is the summary')).toBeInTheDocument()
  })

  it('shows Copy MD and Download buttons', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '# test' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Copy MD')).toBeInTheDocument()
    expect(screen.getByText('Download')).toBeInTheDocument()
  })

  it('shows Include diagrams checkbox', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Include diagrams')).toBeInTheDocument()
  })
})

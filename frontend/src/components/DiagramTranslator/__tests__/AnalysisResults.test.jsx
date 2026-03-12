import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalysisResults from '../../DiagramTranslator/AnalysisResults'

vi.mock('../../DiagramTranslator/ExportPanel', () => ({
  default: (props) => <div data-testid="export-panel">ExportPanel</div>,
}))

vi.mock('../../DiagramTranslator/HLDPanel', () => ({
  default: (props) => <div data-testid="hld-panel">HLDPanel</div>,
}))

describe('AnalysisResults', () => {
  const mockAnalysis = {
    diagram_type: 'AWS Architecture',
    services_detected: 8,
    source_provider: 'aws',
    zones: [
      { id: 1, name: 'Frontend', services: ['CloudFront', 'S3'] },
      { id: 2, name: 'Backend', services: ['EC2', 'RDS'] },
    ],
    mappings: [
      { source_service: 'EC2', azure_service: 'Azure VM', confidence: 0.95, notes: 'Zone 1' },
      { source_service: 'S3', azure_service: 'Blob Storage', confidence: 0.85, notes: 'Zone 1' },
    ],
    confidence_summary: { high: 5, medium: 2, low: 1, average: 0.88 },
    warnings: ['Consider using managed services', 'Review security groups'],
  }

  const defaultProps = {
    analysis: mockAnalysis,
    loading: false,
    iacFormat: 'terraform',
    exportLoading: {},
    hldLoading: false,
    hldData: null,
    hldTab: 'overview',
    hldExportLoading: {},
    hldIncludeDiagrams: true,
    copyFeedback: {},
    onSetStep: vi.fn(),
    onGenerateIac: vi.fn(),
    onGenerateHld: vi.fn(),
    onExportDiagram: vi.fn(),
    onSetHldTab: vi.fn(),
    onSetHldIncludeDiagrams: vi.fn(),
    onHldExport: vi.fn(),
    onCopyWithFeedback: vi.fn(),
  }

  it('renders diagram type title', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('AWS Architecture')).toBeInTheDocument()
  })

  it('shows services detected count', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText(/8 services mapped across 2 zones/)).toBeInTheDocument()
  })

  it('shows provider badges', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('AWS')).toBeInTheDocument()
    expect(screen.getByText('AZURE')).toBeInTheDocument()
  })

  it('shows confidence summary', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('High Confidence')).toBeInTheDocument()
    expect(screen.getByText('88%')).toBeInTheDocument()
  })

  it('renders zone cards', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('Frontend')).toBeInTheDocument()
    expect(screen.getByText('Backend')).toBeInTheDocument()
  })

  it('shows warnings section', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('Warnings and Recommendations')).toBeInTheDocument()
    expect(screen.getByText('Consider using managed services')).toBeInTheDocument()
  })

  it('renders Terraform button', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('Terraform')).toBeInTheDocument()
  })

  it('renders Bicep button', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByText('Bicep')).toBeInTheDocument()
  })

  it('calls onGenerateIac with terraform when Terraform clicked', async () => {
    const user = userEvent.setup()
    render(<AnalysisResults {...defaultProps} />)
    await user.click(screen.getByText('Terraform'))
    expect(defaultProps.onGenerateIac).toHaveBeenCalledWith('terraform')
  })

  it('calls onGenerateIac with bicep when Bicep clicked', async () => {
    const user = userEvent.setup()
    render(<AnalysisResults {...defaultProps} />)
    await user.click(screen.getByText('Bicep'))
    expect(defaultProps.onGenerateIac).toHaveBeenCalledWith('bicep')
  })

  it('renders export panel', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.getByTestId('export-panel')).toBeInTheDocument()
  })
})

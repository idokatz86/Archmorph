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

// Prevent lazy-loaded xyflow components from causing ResizeObserver errors in JSDOM
vi.mock('../../DiagramTranslator/ArchitectureFlow', () => ({
  default: (props) => <div data-testid="architecture-flow">ArchitectureFlow</div>,
}))

vi.mock('../../DiagramTranslator/DependencyGraph', () => ({
  default: (props) => <div data-testid="dependency-graph">DependencyGraph</div>,
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
    onReviewAssumptions: vi.fn(),
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

  it('renders zone cards in map view', async () => {
    const user = userEvent.setup()
    render(<AnalysisResults {...defaultProps} />)
    await user.click(screen.getByText('Map'))
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

  it('does not render deprecated IaC output buttons', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.queryByText('CloudFormation')).not.toBeInTheDocument()
    expect(screen.queryByText('Pulumi')).not.toBeInTheDocument()
    expect(screen.queryByText('AWS CDK')).not.toBeInTheDocument()
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

  it('shows assumptions and review action when available', async () => {
    const user = userEvent.setup()
    const assumptions = [
      { id: 'env_target', question: 'What environment is this architecture for?', assumed_answer: 'Production' },
    ]

    render(<AnalysisResults {...defaultProps} assumptions={assumptions} questionsCount={2} />)

    expect(screen.getByText('Architecture Assumptions')).toBeInTheDocument()
    expect(screen.getByText('Production')).toBeInTheDocument()
    await user.click(screen.getByText('Review assumptions'))
    expect(defaultProps.onReviewAssumptions).toHaveBeenCalledTimes(1)
  })

  // Regression: GPT vision prompt tells the model to emit warnings as
  // `{type, message}` objects. Rendering an object as a child crashes React
  // with error #31. AnalysisResults must coerce object warnings to text.
  it('renders object-shaped warnings without crashing', () => {
    const objectWarnings = {
      ...mockAnalysis,
      warnings: [
        { type: 'potential_mismatch', message: 'Service X may not map cleanly' },
        'plain string still works',
        { description: 'Falls back to description key' },
      ],
    }
    render(<AnalysisResults {...defaultProps} analysis={objectWarnings} />)
    expect(screen.getByText('Service X may not map cleanly')).toBeInTheDocument()
    expect(screen.getByText('plain string still works')).toBeInTheDocument()
    expect(screen.getByText('Falls back to description key')).toBeInTheDocument()
  })

  it('renders object-shaped confidence provenance details without crashing', async () => {
    const user = userEvent.setup()
    const objectDetails = {
      ...mockAnalysis,
      mappings: [
        {
          source_service: 'Lambda',
          azure_service: 'Azure Functions',
          confidence: 0.91,
          notes: 'Zone 1',
          confidence_explanation: [
            { message: 'Runtime capabilities match' },
          ],
          confidence_provenance: {
            feature_parity: {
              parity_score: 'strong',
              matched_features: [{ name: 'Event triggers' }],
              missing_features: [{ message: 'Runtime limit differs' }],
            },
            migration_guidance: {
              estimated_effort: 'medium',
              breaking_changes: [{ description: 'Rewrite deployment package' }],
            },
          },
        },
      ],
    }

    render(<AnalysisResults {...defaultProps} analysis={objectDetails} />)
    await user.click(screen.getByText('Table'))
    await user.click(screen.getByText('Lambda'))

    expect(screen.getByText('Runtime capabilities match')).toBeInTheDocument()
    expect(screen.getByText(/Event triggers/)).toBeInTheDocument()
    expect(screen.getByText(/Runtime limit differs/)).toBeInTheDocument()
    expect(screen.getByText('Rewrite deployment package')).toBeInTheDocument()
  })

  // ── Migration Package primary CTA ──────────────────────────────────────────

  it('does not render migration package CTA when onExportPackage is not provided', () => {
    render(<AnalysisResults {...defaultProps} />)
    expect(screen.queryByTestId('migration-package-cta')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /download migration package/i })).not.toBeInTheDocument()
  })

  it('renders migration package primary CTA when onExportPackage is provided', () => {
    const onExportPackage = vi.fn()
    render(<AnalysisResults {...defaultProps} onExportPackage={onExportPackage} />)
    expect(screen.getByTestId('migration-package-cta')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download migration package/i })).toBeInTheDocument()
  })

  it('calls onExportPackage when migration package button is clicked', async () => {
    const user = userEvent.setup()
    const onExportPackage = vi.fn()
    render(<AnalysisResults {...defaultProps} onExportPackage={onExportPackage} />)
    await user.click(screen.getByRole('button', { name: /download migration package/i }))
    expect(onExportPackage).toHaveBeenCalledTimes(1)
  })

  it('shows what is included in the migration package', () => {
    const onExportPackage = vi.fn()
    render(<AnalysisResults {...defaultProps} onExportPackage={onExportPackage} />)
    const cta = screen.getByTestId('migration-package-cta')
    expect(cta.textContent).toMatch(/executive summary/i)
    expect(cta.textContent).toMatch(/azure mappings/i)
    expect(cta.textContent).toMatch(/cost estimates/i)
  })

  it('shows ai-generated vs confirmed disclaimer in migration package CTA', () => {
    const onExportPackage = vi.fn()
    render(<AnalysisResults {...defaultProps} onExportPackage={onExportPackage} />)
    expect(screen.getByText(/generated recommendations are ai-assisted/i)).toBeInTheDocument()
    expect(screen.getByText(/confirmed/i)).toBeInTheDocument()
  })

  it('renders classic export panel as secondary below migration package CTA', () => {
    const onExportPackage = vi.fn()
    render(<AnalysisResults {...defaultProps} onExportPackage={onExportPackage} />)
    // Both should be present — package CTA first (primary), ExportPanel secondary
    const cta = screen.getByTestId('migration-package-cta')
    const panel = screen.getByTestId('export-panel')
    expect(cta).toBeInTheDocument()
    expect(panel).toBeInTheDocument()
    // CTA should appear before export panel in the DOM
    expect(
      cta.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
  })
})

describe('AnalysisResults — trust/evidence layer (#1130)', () => {
  const baseProps = {
    analysis: {
      diagram_type: 'AWS Architecture',
      services_detected: 3,
      source_provider: 'aws',
      zones: [{ id: 1, name: 'Web', services: ['EC2'] }],
      mappings: [],
      confidence_summary: { high: 2, medium: 1, low: 0, average: 0.88 },
      warnings: [],
    },
    loading: false,
    iacFormat: 'terraform',
    exportLoading: {},
    copyFeedback: {},
    onSetStep: vi.fn(),
    onGenerateIac: vi.fn(),
    onExportDiagram: vi.fn(),
    onCopyWithFeedback: vi.fn(),
    onReviewAssumptions: vi.fn(),
  }

  it('shows needs-review banner when mappings have needs_review=true', () => {
    const analysis = {
      ...baseProps.analysis,
      mappings: [
        { source_service: 'ObscureSvc', azure_service: 'SomeSvc', confidence: 0.55, needs_review: true },
        { source_service: 'EC2', azure_service: 'Virtual Machines', confidence: 0.95, needs_review: false },
      ],
      confidence_summary: { high: 1, medium: 0, low: 1, average: 0.75 },
    }
    const { getByText } = render(<AnalysisResults {...baseProps} analysis={analysis} />)
    expect(getByText(/flagged for review/i)).toBeInTheDocument()
  })

  it('does not show needs-review banner when all mappings are high confidence', () => {
    const analysis = {
      ...baseProps.analysis,
      mappings: [
        { source_service: 'EC2', azure_service: 'Virtual Machines', confidence: 0.95, needs_review: false },
        { source_service: 'S3', azure_service: 'Blob Storage', confidence: 0.92, needs_review: false },
      ],
      confidence_summary: { high: 2, medium: 0, low: 0, average: 0.93 },
    }
    const { queryByText } = render(<AnalysisResults {...baseProps} analysis={analysis} />)
    expect(queryByText(/flagged for review/i)).not.toBeInTheDocument()
  })

  it('shows "Needs review" badge in mapping row when needs_review is true', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['ObscureSvc'] }],
      mappings: [
        {
          source_service: 'ObscureSvc',
          azure_service: 'SomeSvc',
          confidence: 0.55,
          needs_review: true,
          notes: 'Zone 1',
        },
      ],
      confidence_summary: { high: 0, medium: 0, low: 1, average: 0.55 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    expect(screen.getByText('Needs review')).toBeInTheDocument()
  })

  it('shows evidence panel when mapping has evidence with rationale', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['Lambda'] }],
      mappings: [
        {
          source_service: 'Lambda',
          azure_service: 'Azure Functions',
          confidence: 0.95,
          needs_review: false,
          notes: 'Zone 1',
          evidence: {
            detection_source: 'catalogue',
            detection_confidence: 0.95,
            rationale: 'Azure Functions is the recommended Azure equivalent for Lambda.',
            alternatives_considered: [
              { azure_service: 'Container Apps', confidence: 0.80, rationale: 'Alternative option' },
            ],
            known_gaps: ['Provisioned Concurrency requires Premium plan'],
            catalog_freshness: '2026-05-03',
            user_override: false,
            user_confirmed: true,
            needs_review: false,
            run_id: 'test-run',
            generated_at: '2026-05-25T12:00:00Z',
          },
        },
      ],
      confidence_summary: { high: 1, medium: 0, low: 0, average: 0.93 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    // Click the confidence badge (getAllByText handles the confidence summary + badge)
    const badges = screen.getAllByText('95%')
    await user.click(badges[badges.length - 1])
    expect(screen.getByText('Mapping Evidence & Rationale')).toBeInTheDocument()
    expect(screen.getByText(/Azure Functions is the recommended/)).toBeInTheDocument()
  })

  it('shows alternatives considered in evidence panel', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['Lambda'] }],
      mappings: [
        {
          source_service: 'Lambda',
          azure_service: 'Azure Functions',
          confidence: 0.95,
          needs_review: false,
          notes: 'Zone 1',
          evidence: {
            detection_source: 'catalogue',
            detection_confidence: 0.95,
            rationale: 'Azure Functions is the recommended Azure equivalent for Lambda.',
            alternatives_considered: [
              { azure_service: 'Container Apps', confidence: 0.80, rationale: 'Containerized option' },
            ],
            known_gaps: [],
            catalog_freshness: '2026-05-03',
            user_override: false,
            user_confirmed: true,
            needs_review: false,
            run_id: '',
            generated_at: '2026-05-25T12:00:00Z',
          },
        },
      ],
      confidence_summary: { high: 1, medium: 0, low: 0, average: 0.93 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    const badges = screen.getAllByText('95%')
    await user.click(badges[badges.length - 1])
    expect(screen.getByText('Alternatives considered')).toBeInTheDocument()
    expect(screen.getByText('Container Apps')).toBeInTheDocument()
  })

  it('shows known gaps in evidence panel', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['Lambda'] }],
      mappings: [
        {
          source_service: 'Lambda',
          azure_service: 'Azure Functions',
          confidence: 0.88,
          needs_review: false,
          notes: 'Zone 1',
          evidence: {
            detection_source: 'ai',
            detection_confidence: 0.88,
            rationale: 'Azure Functions mapped via AI analysis.',
            alternatives_considered: [],
            known_gaps: ['Provisioned Concurrency requires Premium plan'],
            catalog_freshness: null,
            user_override: false,
            user_confirmed: false,
            needs_review: false,
            run_id: '',
            generated_at: '2026-05-25T12:00:00Z',
          },
        },
      ],
      confidence_summary: { high: 0, medium: 1, low: 0, average: 0.85 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    const badges = screen.getAllByText('88%')
    await user.click(badges[badges.length - 1])
    expect(screen.getByText('Known gaps')).toBeInTheDocument()
    expect(screen.getByText('Provisioned Concurrency requires Premium plan')).toBeInTheDocument()
  })

  it('shows user-confirmed status in evidence panel', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['EC2'] }],
      mappings: [
        {
          source_service: 'EC2',
          azure_service: 'Virtual Machines',
          confidence: 0.95,
          needs_review: false,
          notes: 'Zone 1',
          evidence: {
            detection_source: 'user',
            detection_confidence: 1.0,
            rationale: 'Virtual Machines was manually specified by the user.',
            alternatives_considered: [],
            known_gaps: [],
            catalog_freshness: '2026-05-03',
            user_override: true,
            user_confirmed: true,
            needs_review: false,
            run_id: '',
            generated_at: '2026-05-25T12:00:00Z',
          },
        },
      ],
      confidence_summary: { high: 1, medium: 0, low: 0, average: 0.93 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    const badges = screen.getAllByText('95%')
    await user.click(badges[badges.length - 1])
    expect(screen.getByText('User confirmed')).toBeInTheDocument()
  })

  it('renders object-shaped evidence fields without crashing', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseProps.analysis,
      zones: [{ id: 1, name: 'Web', services: ['Lambda'] }],
      mappings: [
        {
          source_service: 'Lambda',
          azure_service: 'Azure Functions',
          confidence: 0.95,
          notes: 'Zone 1',
          evidence: {
            detection_source: { label: 'catalogue' },
            rationale: { message: 'Object rationale rendered safely' },
            alternatives_considered: [
              { azure_service: { name: 'Container Apps' }, notes: { message: 'Object note rendered safely' } },
            ],
            known_gaps: [{ message: 'Object gap rendered safely' }],
            catalog_freshness: { value: '2026-05-03' },
            user_confirmed: true,
            needs_review: false,
          },
        },
      ],
      confidence_summary: { high: 1, medium: 0, low: 0, average: 0.95 },
    }
    render(<AnalysisResults {...baseProps} analysis={analysis} />)
    await user.click(screen.getByText('Map'))
    const badges = screen.getAllByText('95%')
    await user.click(badges[badges.length - 1])
    expect(screen.getByText('Object rationale rendered safely')).toBeInTheDocument()
    expect(screen.getByText(/Object note rendered safely/)).toBeInTheDocument()
    expect(screen.getByText('Object gap rendered safely')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TemplateGallery from '../TemplateGallery'
import useAppStore from '../../stores/useAppStore'

function mockJsonResponse(data) {
  return {
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
  }
}

const starterResponse = {
  templates: [
    {
      id: 'aws-iaas-web',
      title: 'AWS IaaS Web Stack',
      description: 'Load-balanced web and database starter.',
      category: 'web',
      complexity: 'intermediate',
      source_provider: 'aws',
      services: ['VPC', 'ELB', 'EC2', 'RDS'],
      tags: ['web', 'iaas'],
      available_deliverables: ['Analysis', 'IaC', 'HLD', 'Cost Estimate', 'Export Package'],
      expected_outputs: ['Azure VM/App Gateway mapping', 'Bicep or Terraform IaC'],
      regression_profile: { id: 'golden-aws-iaas-web', coverage: 'golden', manual_check: true },
    },
    {
      id: 'gcp-gke-platform',
      title: 'GCP Container Platform',
      description: 'GKE and Pub/Sub starter.',
      category: 'containers',
      complexity: 'advanced',
      source_provider: 'gcp',
      services: ['GKE', 'Pub/Sub', 'Firestore'],
      tags: ['containers'],
      available_deliverables: ['Analysis', 'IaC', 'HLD'],
      expected_outputs: ['AKS/ACA decision baseline'],
      regression_profile: { id: 'golden-gcp-gke-platform', coverage: 'golden', manual_check: true },
    },
  ],
  categories: [
    { id: 'all', label: 'All Starters', count: 2 },
    { id: 'web', label: 'Web & APIs', count: 1 },
    { id: 'containers', label: 'Containers', count: 1 },
  ],
  total: 2,
}

describe('TemplateGallery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAppStore.setState({ activeTab: 'templates', pendingTemplateAnalysis: null })
    fetch.mockResolvedValue(mockJsonResponse(starterResponse))
  })

  it('frames templates as starter architectures with regression metadata', async () => {
    render(<TemplateGallery />)

    expect(await screen.findByRole('heading', { name: 'Starter Architectures' })).toBeInTheDocument()
    expect(screen.getByText('AWS IaaS Web Stack')).toBeInTheDocument()
    expect(screen.getAllByText('regression-ready')).toHaveLength(2)
    expect(screen.getByText('5 deliverables')).toBeInTheDocument()
    expect(screen.getByText('Azure VM/App Gateway mapping')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Open in Workbench' })).toHaveLength(2)
  })

  it('searches starter metadata and deliverables', async () => {
    const user = userEvent.setup()
    render(<TemplateGallery />)

    await screen.findByText('AWS IaaS Web Stack')
    await user.type(screen.getByPlaceholderText('Search starters'), 'pub/sub')

    expect(screen.getByText('GCP Container Platform')).toBeInTheDocument()
    expect(screen.queryByText('AWS IaaS Web Stack')).not.toBeInTheDocument()
  })

  it('opens a starter directly in the Workbench workflow', async () => {
    const user = userEvent.setup()
    fetch
      .mockResolvedValueOnce(mockJsonResponse(starterResponse))
      .mockResolvedValueOnce(mockJsonResponse({ diagram_id: 'template-aws-iaas-web-123', is_starter: true }))

    render(<TemplateGallery />)

    const [firstStarterAction] = await screen.findAllByRole('button', { name: 'Open in Workbench' })
    await user.click(firstStarterAction)

    await waitFor(() => {
      expect(useAppStore.getState().activeTab).toBe('translator')
      expect(useAppStore.getState().pendingTemplateAnalysis).toEqual({ diagram_id: 'template-aws-iaas-web-123', is_starter: true })
    })
    expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('/templates/aws-iaas-web/analyze'), expect.objectContaining({ method: 'POST' }))
  })
})

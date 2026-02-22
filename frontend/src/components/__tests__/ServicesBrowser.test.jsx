import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ServicesBrowser from '../ServicesBrowser'

describe('ServicesBrowser', () => {
  const mockServices = [
    { name: 'EC2', description: 'Virtual servers', provider: 'aws', category: 'Compute' },
    { name: 'Azure VM', description: 'Virtual machines', provider: 'azure', category: 'Compute' },
    { name: 'Cloud SQL', description: 'Managed SQL', provider: 'gcp', category: 'Database' },
  ]
  const mockStats = { totalServices: 3, totalMappings: 10, categories: 2, avgConfidence: 0.85 }
  const mockCategories = { categories: ['Compute', 'Database'] }

  beforeEach(() => {
    vi.clearAllMocks()
    fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ services: mockServices }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockStats) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockCategories) })
  })

  it('shows loading state initially', () => {
    render(<ServicesBrowser />)
    // The spinner is an SVG from lucide-react with animate-spin class
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders stats after loading', async () => {
    render(<ServicesBrowser />)
    expect(await screen.findByText('3')).toBeInTheDocument()
    expect(screen.getByText('Total Services')).toBeInTheDocument()
  })

  it('renders service cards', async () => {
    render(<ServicesBrowser />)
    expect(await screen.findByText('EC2')).toBeInTheDocument()
    expect(screen.getByText('Azure VM')).toBeInTheDocument()
    expect(screen.getByText('Cloud SQL')).toBeInTheDocument()
  })

  it('displays search input', async () => {
    render(<ServicesBrowser />)
    await screen.findByText('EC2')
    expect(screen.getByPlaceholderText('Search services...')).toBeInTheDocument()
  })

  it('filters services by search text', async () => {
    const user = userEvent.setup()
    render(<ServicesBrowser />)
    await screen.findByText('EC2')
    await user.type(screen.getByPlaceholderText('Search services...'), 'Azure')
    expect(screen.getByText('Azure VM')).toBeInTheDocument()
    expect(screen.queryByText('EC2')).not.toBeInTheDocument()
  })

  it('shows services count after filtering', async () => {
    const user = userEvent.setup()
    render(<ServicesBrowser />)
    await screen.findByText('EC2')
    await user.type(screen.getByPlaceholderText('Search services...'), 'Cloud')
    expect(screen.getByText('1 services found')).toBeInTheDocument()
  })

  it('handles API error gracefully', async () => {
    fetch.mockReset()
    fetch.mockRejectedValue(new Error('API Error'))
    render(<ServicesBrowser />)
    await waitFor(() => {
      expect(document.querySelector('.animate-spin')).not.toBeInTheDocument()
    })
  })
})

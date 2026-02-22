import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Roadmap from '../Roadmap'

describe('Roadmap', () => {
  const mockRoadmap = {
    stats: {
      total_releases: 5,
      features_shipped: 30,
      days_since_launch: 100,
      current_version: 'v2.12.0',
    },
    timeline: {
      released: [
        { version: 'v2.12.0', name: 'Latest Release', status: 'released', date: '2026-02-01', highlights: ['Feature A'] },
        { version: 'v2.11.0', name: 'Previous Release', status: 'released', date: '2026-01-15', highlights: ['Feature B'] },
      ],
      in_progress: [
        { version: 'v2.13.0', name: 'Current Sprint', status: 'in_progress', highlights: ['WIP feature'] },
      ],
      planned: [
        { version: 'v3.0.0', name: 'Next Major', status: 'planned', highlights: ['Big change'] },
      ],
      ideas: [
        { version: 'idea-1', name: 'Maybe Later', status: 'idea', highlights: ['Cool idea'] },
      ],
    },
  }

  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({
      json: () => Promise.resolve(mockRoadmap),
    })
  })

  it('shows loading spinner initially', () => {
    render(<Roadmap />)
    expect(document.querySelector('.animate-spin')).toBeInTheDocument()
  })

  it('renders roadmap title after loading', async () => {
    render(<Roadmap />)
    expect(await screen.findByText('Roadmap & Timeline')).toBeInTheDocument()
  })

  it('displays stats cards', async () => {
    render(<Roadmap />)
    expect(await screen.findByText('5')).toBeInTheDocument()
    expect(screen.getByText('Releases Shipped')).toBeInTheDocument()
    expect(screen.getByText('30')).toBeInTheDocument()
    const versionElements = screen.getAllByText('v2.12.0')
    expect(versionElements.length).toBeGreaterThan(0)
  })

  it('shows filter buttons', async () => {
    render(<Roadmap />)
    await screen.findByText('Roadmap & Timeline')
    expect(screen.getByText('All')).toBeInTheDocument()
    const releasedElements = screen.getAllByText('Released')
    expect(releasedElements.length).toBeGreaterThan(0)
    const plannedElements = screen.getAllByText('Planned')
    expect(plannedElements.length).toBeGreaterThan(0)
    expect(screen.getByText('Ideas')).toBeInTheDocument()
  })

  it('shows Request Feature button', async () => {
    render(<Roadmap />)
    expect(await screen.findByText('Request Feature')).toBeInTheDocument()
  })

  it('shows Report Bug button', async () => {
    render(<Roadmap />)
    expect(await screen.findByText('Report Bug')).toBeInTheDocument()
  })

  it('shows in-progress section', async () => {
    render(<Roadmap />)
    const inProgressElements = await screen.findAllByText('In Progress')
    expect(inProgressElements.length).toBeGreaterThan(0)
    expect(screen.getByText('Current Sprint')).toBeInTheDocument()
  })

  it('handles API error gracefully', async () => {
    fetch.mockRejectedValue(new Error('Server error'))
    render(<Roadmap />)
    expect(await screen.findByText(/Failed to load roadmap/)).toBeInTheDocument()
    expect(screen.getByText('Retry')).toBeInTheDocument()
  })

  it('opens feature request modal', async () => {
    const user = userEvent.setup()
    render(<Roadmap />)
    await screen.findByText('Request Feature')
    await user.click(screen.getByText('Request Feature'))
    expect(screen.getByText('Request a Feature')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ResultsTable from '../ResultsTable'

const baseAnalysis = {
  source_provider: 'aws',
  mappings: [
    {
      source_service: 'EC2',
      azure_service: 'Azure VM',
      confidence: 0.92,
      migration_effort: 'medium',
    },
  ],
}

describe('ResultsTable', () => {
  it('renders view toggle buttons', () => {
    render(
      <ResultsTable
        analysis={baseAnalysis}
        activeView="card"
        onViewChange={vi.fn()}
      />
    )
    expect(screen.getByText('Cards')).toBeInTheDocument()
    expect(screen.getByText('Table')).toBeInTheDocument()
  })

  it('renders source and target services in card view', () => {
    render(
      <ResultsTable
        analysis={baseAnalysis}
        activeView="card"
        onViewChange={vi.fn()}
      />
    )
    expect(screen.getByText('EC2')).toBeInTheDocument()
    expect(screen.getByText('Azure VM')).toBeInTheDocument()
  })

  // Regression: React #31 — confidence_explanation items can be objects from
  // backend GPT responses. ResultsTable must coerce them via toRenderableString.
  it('renders object-shaped confidence_explanation without crashing (table row expand)', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseAnalysis,
      mappings: [
        {
          source_service: 'EC2',
          azure_service: 'Azure VM',
          confidence: 0.92,
          migration_effort: 'medium',
          confidence_explanation: [
            { type: 'factor', message: 'Direct compute equivalent' },
            'plain string reason',
            { name: 'Mature migration tooling available' },
          ],
        },
      ],
    }
    render(
      <ResultsTable
        analysis={analysis}
        activeView="table"
        onViewChange={vi.fn()}
      />
    )

    // Click the table row to expand detail
    const row = screen.getByText('EC2').closest('tr')
    await user.click(row)

    expect(screen.getByText('Direct compute equivalent')).toBeInTheDocument()
    expect(screen.getByText('plain string reason')).toBeInTheDocument()
    expect(screen.getByText('Mature migration tooling available')).toBeInTheDocument()
  })

  // Regression: React #31 — feature parity arrays can contain objects
  it('renders object-shaped feature_parity matched/missing features without crashing', async () => {
    const user = userEvent.setup()
    const analysis = {
      ...baseAnalysis,
      mappings: [
        {
          source_service: 'RDS',
          azure_service: 'Azure SQL',
          confidence: 0.85,
          migration_effort: 'low',
          confidence_provenance: {
            feature_parity: {
              parity_score: '85%',
              matched_features: [
                { name: 'ACID transactions' },
                'read replicas',
              ],
              missing_features: [
                { message: 'Oracle-specific stored procedures' },
                'pg_cron extension',
              ],
            },
          },
        },
      ],
    }
    render(
      <ResultsTable
        analysis={analysis}
        activeView="table"
        onViewChange={vi.fn()}
      />
    )

    // Click the table row to expand detail
    const row = screen.getByText('RDS').closest('tr')
    await user.click(row)

    expect(screen.getByText(/ACID transactions/)).toBeInTheDocument()
    expect(screen.getByText(/read replicas/)).toBeInTheDocument()
    expect(screen.getByText(/Oracle-specific stored procedures/)).toBeInTheDocument()
    expect(screen.getByText(/pg_cron extension/)).toBeInTheDocument()
  })
})

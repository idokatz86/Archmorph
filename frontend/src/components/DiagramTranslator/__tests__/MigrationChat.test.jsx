import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock the api client BEFORE importing the component so the module
// graph picks up the mock.
vi.mock('../../../services/apiClient', () => ({
  default: { post: vi.fn() },
}))

import api from '../../../services/apiClient'
import MigrationChat from '../MigrationChat'

describe('MigrationChat — React #31 guard', () => {
  beforeEach(() => {
    api.post.mockReset()
  })

  it('renders extracted strings when backend returns object-shaped related_services', async () => {
    // Simulate a misbehaving backend response (the exact shape that
    // crashed production with React error #31 before #635).
    api.post.mockResolvedValueOnce({
      reply: 'Use Azure SQL and Cosmos DB.',
      related_services: [
        { type: 'database', message: 'Azure SQL' },
        { name: 'Cosmos DB' },
        'Azure Cache for Redis',
      ],
    })

    const user = userEvent.setup()
    render(<MigrationChat diagramId="diag-1" />)

    // Open the chat panel.
    await user.click(screen.getByLabelText('Open Migration Advisor'))

    // Send a question.
    const input = screen.getByPlaceholderText(/ask about/i)
    await user.type(input, 'What database should I use?')
    await user.keyboard('{Enter}')

    // No crash + the extracted strings render as <Badge>s.
    await waitFor(() => {
      expect(screen.getByText('Azure SQL')).toBeInTheDocument()
      expect(screen.getByText('Cosmos DB')).toBeInTheDocument()
      expect(screen.getByText('Azure Cache for Redis')).toBeInTheDocument()
    })
  })

  it('renders strings unchanged when backend returns plain strings', async () => {
    api.post.mockResolvedValueOnce({
      reply: 'Use Azure SQL.',
      related_services: ['Azure SQL', 'Azure Cache for Redis'],
    })

    const user = userEvent.setup()
    render(<MigrationChat diagramId="diag-2" />)

    await user.click(screen.getByLabelText('Open Migration Advisor'))
    const input = screen.getByPlaceholderText(/ask about/i)
    await user.type(input, 'Q?')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText('Azure SQL')).toBeInTheDocument()
      expect(screen.getByText('Azure Cache for Redis')).toBeInTheDocument()
    })
  })

  it('skips items with no extractable string instead of crashing', async () => {
    api.post.mockResolvedValueOnce({
      reply: 'OK.',
      related_services: [
        { unrelated: 'meta' }, // no known key — falls back to JSON.stringify
        '',                    // empty string is dropped
        null,                  // null is dropped
        'Azure Functions',
      ],
    })

    const user = userEvent.setup()
    render(<MigrationChat diagramId="diag-3" />)

    await user.click(screen.getByLabelText('Open Migration Advisor'))
    const input = screen.getByPlaceholderText(/ask about/i)
    await user.type(input, 'Q?')
    await user.keyboard('{Enter}')

    await waitFor(() => {
      expect(screen.getByText('Azure Functions')).toBeInTheDocument()
    })
    // Component did not throw — assertion above implies render succeeded.
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from '../App'

// Mock child components to isolate App tests
vi.mock('../components/Nav', () => ({
  default: ({ activeTab, setActiveTab }) => (
    <nav data-testid="nav">
      <button onClick={() => setActiveTab('services')}>Services</button>
      <button onClick={() => setActiveTab('roadmap')}>Roadmap</button>
      <button onClick={() => setActiveTab('translator')}>Translator</button>
    </nav>
  ),
}))
vi.mock('../components/DiagramTranslator', () => ({
  default: () => <div data-testid="translator">DiagramTranslator</div>,
}))
vi.mock('../components/ServicesBrowser', () => ({
  default: () => <div data-testid="services">ServicesBrowser</div>,
}))
vi.mock('../components/Roadmap', () => ({
  default: () => <div data-testid="roadmap">Roadmap</div>,
}))
vi.mock('../components/ChatWidget', () => ({
  default: () => <div data-testid="chat-widget">ChatWidget</div>,
}))
vi.mock('../components/AdminDashboard', () => ({
  default: ({ onClose }) => <div data-testid="admin-dashboard"><button onClick={onClose}>Close</button></div>,
}))
vi.mock('../components/ErrorBoundary', () => ({
  default: ({ children }) => <div data-testid="error-boundary">{children}</div>,
}))

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockResolvedValue({ json: () => Promise.resolve({}) })
  })

  it('renders without crashing', () => {
    render(<App />)
    expect(screen.getByTestId('nav')).toBeInTheDocument()
  })

  it('shows translator tab by default', () => {
    render(<App />)
    expect(screen.getByTestId('translator')).toBeInTheDocument()
  })

  it('renders the beta preview banner', () => {
    render(<App />)
    expect(screen.getByText(/Beta Preview/)).toBeInTheDocument()
  })

  it('renders footer with version info', () => {
    render(<App />)
    expect(screen.getByText(/Archmorph v/)).toBeInTheDocument()
  })

  it('renders chat widget', async () => {
    render(<App />)
    expect(await screen.findByTestId('chat-widget')).toBeInTheDocument()
  })

  it('fetches service-updates status on mount', () => {
    render(<App />)
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/service-updates/status'),
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    )
  })

  it('switches to services tab when nav triggers it', async () => {
    const { getByText } = render(<App />)
    await getByText('Services').click()
    expect(await screen.findByTestId('services')).toBeInTheDocument()
    expect(screen.queryByTestId('translator')).not.toBeInTheDocument()
  })

  it('switches to roadmap tab', async () => {
    const { getByText } = render(<App />)
    await getByText('Roadmap').click()
    expect(await screen.findByTestId('roadmap')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import useAppStore from '../stores/useAppStore'

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
vi.mock('../components/LandingPage', () => ({
  default: ({ onGetStarted }) => <div data-testid="landing"><button onClick={onGetStarted}>Get Started</button></div>,
}))
vi.mock('../components/LegalPages', () => ({
  default: () => <div data-testid="legal">LegalPages</div>,
}))
vi.mock('../components/CookieBanner', () => ({
  default: () => null,
}))
vi.mock('../components/OnboardingTour', () => ({
  default: () => null,
}))
vi.mock('../components/Auth', () => ({
  AuthProvider: ({ children }) => <>{children}</>,
}))
// PricingPage removed — feature temporarily disabled

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState(null, '', '/')
    useAppStore.setState({ activeTab: 'landing', adminOpen: false, updateStatus: null, pendingResumeId: null })
    fetch.mockResolvedValue({ json: () => Promise.resolve({}) })
  })

  const renderSettledApp = async () => {
    const result = render(<App />)
    await screen.findByTestId('landing')
    await screen.findByTestId('chat-widget')
    return result
  }

  it('renders without crashing', async () => {
    await renderSettledApp()
    expect(screen.getByTestId('nav')).toBeInTheDocument()
  })

  it('shows landing page by default', async () => {
    await renderSettledApp()
    // Default tab is now 'landing' (#211)
    expect(screen.queryByTestId('translator')).not.toBeInTheDocument()
  })

  it('does not render a beta preview banner', async () => {
    await renderSettledApp()
    expect(screen.queryByText(/Beta Preview/)).not.toBeInTheDocument()
  })

  it('renders footer with version info', async () => {
    await renderSettledApp()
    expect(screen.getByText(/Archmorph v/)).toBeInTheDocument()
  })

  it('renders chat widget', async () => {
    await renderSettledApp()
    expect(await screen.findByTestId('chat-widget')).toBeInTheDocument()
  })

  it('fetches service-updates status on mount', async () => {
    await renderSettledApp()
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/service-updates/status'),
        expect.objectContaining({ signal: expect.any(AbortSignal) })
      )
    })
  })

  it('switches to services tab when nav triggers it', async () => {
    const user = userEvent.setup()
    const { getByText } = await renderSettledApp()
    await user.click(getByText('Services'))
    expect(await screen.findByTestId('services')).toBeInTheDocument()
    expect(screen.queryByTestId('translator')).not.toBeInTheDocument()
  })

  it('switches to roadmap tab', async () => {
    const user = userEvent.setup()
    const { getByText } = await renderSettledApp()
    await user.click(getByText('Roadmap'))
    expect(await screen.findByTestId('roadmap')).toBeInTheDocument()
  })
})

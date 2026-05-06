import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock Prism before importing IaCViewer
vi.mock('prismjs', () => ({
  default: {
    highlight: vi.fn((code) => code),
    languages: { hcl: {}, json: {} },
  },
}))
vi.mock('prismjs/components/prism-hcl', () => ({}))
vi.mock('prismjs/components/prism-json', () => ({}))

import IaCViewer from '../../DiagramTranslator/IaCViewer'

describe('IaCViewer', () => {
  const defaultProps = {
    iacCode: 'resource "azurerm_resource_group" "rg" {\n  name     = "my-rg"\n  location = "eastus"\n}',
    iacFormat: 'terraform',
    copyFeedback: {},
    iacChatOpen: false,
    iacChatMessages: [{ role: 'assistant', content: 'Hello' }],
    iacChatInput: '',
    iacChatLoading: false,
    iacChatEndRef: { current: null },
    iacChatInputRef: { current: null },
    onCopyWithFeedback: vi.fn(),
    onToggleChat: vi.fn(),
    onOpenChatWithMessage: vi.fn(),
    onResetChat: vi.fn(),
    onSendChat: vi.fn(),
    onSetChatInput: vi.fn(),
  }

  it('renders Terraform Code title', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('Terraform Code')).toBeInTheDocument()
  })

  it('renders Bicep Code title when format is bicep', () => {
    render(<IaCViewer {...defaultProps} iacFormat="bicep" />)
    expect(screen.getByText('Bicep Code')).toBeInTheDocument()
  })

  it('falls back deprecated format labels to Terraform Code', () => {
    render(<IaCViewer {...defaultProps} iacFormat="cloudformation" />)
    expect(screen.getByText('Terraform Code')).toBeInTheDocument()
    expect(screen.queryByText('CloudFormation Code')).not.toBeInTheDocument()
  })

  it('shows line count', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('4 lines generated')).toBeInTheDocument()
  })

  it('renders Copy and Download buttons', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('Copy')).toBeInTheDocument()
    expect(screen.getByText('Download')).toBeInTheDocument()
  })

  it('renders IaC Assistant section', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('IaC Assistant')).toBeInTheDocument()
  })

  it('shows quick action buttons when chat is closed', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('Add VNet & Subnets')).toBeInTheDocument()
    expect(screen.getByText('Add Public IPs')).toBeInTheDocument()
    expect(screen.getByText('Add Storage Account')).toBeInTheDocument()
  })

  it('shows Open Chat button when chat is closed', () => {
    render(<IaCViewer {...defaultProps} />)
    expect(screen.getByText('Open Chat')).toBeInTheDocument()
  })

  it('shows Close Chat button when chat is open', () => {
    render(<IaCViewer {...defaultProps} iacChatOpen={true} />)
    expect(screen.getByText('Close Chat')).toBeInTheDocument()
  })

  it('calls onToggleChat when Open Chat is clicked', async () => {
    const user = userEvent.setup()
    render(<IaCViewer {...defaultProps} />)
    await user.click(screen.getByText('Open Chat'))
    expect(defaultProps.onToggleChat).toHaveBeenCalledTimes(1)
  })

  it('calls onOpenChatWithMessage when quick action is clicked', async () => {
    const user = userEvent.setup()
    render(<IaCViewer {...defaultProps} />)
    await user.click(screen.getByText('Add VNet & Subnets'))
    expect(defaultProps.onOpenChatWithMessage).toHaveBeenCalledTimes(1)
  })

  it('renders chat messages when chat is open', () => {
    render(<IaCViewer {...defaultProps} iacChatOpen={true} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  // Regression: React error #31 — backend chat handler occasionally returns
  // changes/services as objects (e.g. {type, message}) instead of strings.
  // Rendering them directly would crash with "Objects are not valid as a
  // React child". The component must coerce safely.
  it('renders changes/services even when items are objects (React #31 guard)', () => {
    const messageWithObjects = {
      role: 'assistant',
      content: 'Updated.',
      changes: [
        { type: 'add', message: 'Added VNet' },
        'plain string',
        { name: 'Subnet' },
      ],
      services: [{ message: 'Azure VNet' }, 'NSG'],
    }
    render(
      <IaCViewer
        {...defaultProps}
        iacChatOpen={true}
        iacChatMessages={[messageWithObjects]}
      />
    )
    // No crash + the extracted strings are visible.
    expect(screen.getByText('Added VNet')).toBeInTheDocument()
    expect(screen.getByText('plain string')).toBeInTheDocument()
    expect(screen.getByText('Subnet')).toBeInTheDocument()
    expect(screen.getByText('Azure VNet')).toBeInTheDocument()
    expect(screen.getByText('NSG')).toBeInTheDocument()
  })
})

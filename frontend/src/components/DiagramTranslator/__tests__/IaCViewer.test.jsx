import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
})

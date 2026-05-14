import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import UploadStep from '../../DiagramTranslator/UploadStep'

describe('UploadStep', () => {
  const defaultProps = {
    dragOver: false,
    selectedFile: null,
    filePreviewUrl: null,
    fileInputRef: React.createRef(),
    onDragOver: vi.fn(),
    onDragLeave: vi.fn(),
    onDrop: vi.fn(),
    onFileSelect: vi.fn(),
    onUpload: vi.fn(),
    onRemoveFile: vi.fn(),
    onLoadSample: vi.fn(),
  }

  it('renders the upload title', () => {
    render(<UploadStep {...defaultProps} />)
    expect(screen.getByText('Upload Architecture Diagram')).toBeInTheDocument()
  })

  it('shows drag & drop instructions', () => {
    render(<UploadStep {...defaultProps} />)
    expect(screen.getByText(/Drag & drop your AWS or GCP diagram/)).toBeInTheDocument()
  })

  it('shows file format info', () => {
    render(<UploadStep {...defaultProps} />)
    expect(screen.getByText(/Supports PNG, JPG, JPEG, SVG, PDF, Draw\.io, Visio/)).toBeInTheDocument()
  })

  it('renders sample diagram buttons', () => {
    render(<UploadStep {...defaultProps} />)
    expect(screen.getByText('Hub & Spoke')).toBeInTheDocument()
    expect(screen.getByText('GKE Cluster')).toBeInTheDocument()
    expect(screen.getByText('Classic Web App')).toBeInTheDocument()
    expect(screen.getByText('Microservices')).toBeInTheDocument()
  })

  it('calls onLoadSample when sample button is clicked', async () => {
    const user = userEvent.setup()
    render(<UploadStep {...defaultProps} />)
    await user.click(screen.getByText('Hub & Spoke'))
    expect(defaultProps.onLoadSample).toHaveBeenCalledTimes(1)
    expect(defaultProps.onLoadSample).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'aws-hub-spoke', provider: 'aws' })
    )
  })

  it('shows file name when a file is selected', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('diagram.png')).toBeInTheDocument()
  })

  it('shows Analyze button when file is selected and user is authenticated', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} isAuthenticated={true} />)
    expect(screen.getByText('Analyze This Diagram')).toBeInTheDocument()
  })

  it('shows Analyze button when file is selected and isAuthenticated is omitted (defaults to true)', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('Analyze This Diagram')).toBeInTheDocument()
  })

  it('shows Remove button when file is selected', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('Remove')).toBeInTheDocument()
  })

  it('shows Replace file button when file is selected', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('Replace file')).toBeInTheDocument()
  })

  it('shows file preview image when preview URL provided', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} filePreviewUrl="blob:preview" />)
    expect(screen.getByAltText('Preview')).toBeInTheDocument()
  })

  it('has a hidden file input', () => {
    render(<UploadStep {...defaultProps} />)
    const fileInput = screen.getByLabelText('Select architecture diagram file')
    expect(fileInput).toBeInTheDocument()
    expect(fileInput).toHaveClass('hidden')
  })

  // Accessibility: no nested interactive controls when a file is selected
  it('drop zone does not have role="button" when a file is selected', () => {
    const file = new File(['test'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    // There should be no element with role="button" that contains another interactive control
    const buttons = screen.getAllByRole('button')
    buttons.forEach((btn) => {
      const nestedButtons = within(btn).queryAllByRole('button')
      expect(nestedButtons).toHaveLength(0)
    })
  })

  it('drop zone has role="button" only when no file is selected', () => {
    const { rerender } = render(<UploadStep {...defaultProps} />)
    // No file: drop zone is a button
    expect(screen.getByRole('button', { name: /Upload architecture diagram/i })).toBeInTheDocument()

    // File selected: drop zone is NOT a button
    const file = new File(['test'], 'diagram.pdf', { type: 'application/pdf' })
    rerender(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.queryByRole('button', { name: /Upload architecture diagram/i })).not.toBeInTheDocument()
  })

  it('clicking Analyze calls onUpload with the selected file', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn()
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} onUpload={onUpload} />)
    await user.click(screen.getByRole('button', { name: /Analyze This Diagram/i }))
    expect(onUpload).toHaveBeenCalledTimes(1)
    expect(onUpload).toHaveBeenCalledWith(file)
  })

  it('clicking Remove calls onRemoveFile', async () => {
    const user = userEvent.setup()
    const onRemoveFile = vi.fn()
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} onRemoveFile={onRemoveFile} />)
    await user.click(screen.getByRole('button', { name: /Remove/i }))
    expect(onRemoveFile).toHaveBeenCalledTimes(1)
  })

  it('action buttons appear in visual order: Analyze, Remove, Replace file', () => {
    const file = new File(['test'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    const actionsContainer = screen.getByTestId('file-action-buttons')
    const actionButtons = within(actionsContainer).getAllByRole('button')
    expect(actionButtons.map((b) => b.textContent?.trim())).toEqual([
      'Analyze This Diagram',
      'Remove',
      'Replace file',
    ])
  })

  // ── Auth gate ──

  it('shows "Sign in to analyze" instead of "Analyze This Diagram" when user is signed out and a file is selected', () => {
    const file = new File(['diagram.pdf'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} isAuthenticated={false} onSignIn={vi.fn()} />)
    expect(screen.getByText('Sign in to analyze')).toBeInTheDocument()
    expect(screen.queryByText('Analyze This Diagram')).not.toBeInTheDocument()
  })

  it('calls onSignIn when "Sign in to analyze" button is clicked', async () => {
    const user = userEvent.setup()
    const onSignIn = vi.fn()
    const file = new File(['diagram.pdf'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} isAuthenticated={false} onSignIn={onSignIn} />)
    await user.click(screen.getByText('Sign in to analyze'))
    expect(onSignIn).toHaveBeenCalledTimes(1)
  })

  it('does not call onUpload when "Sign in to analyze" is clicked (auth gate blocks upload)', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn()
    const onSignIn = vi.fn()
    const file = new File(['diagram.pdf'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} isAuthenticated={false} onUpload={onUpload} onSignIn={onSignIn} />)
    await user.click(screen.getByText('Sign in to analyze'))
    expect(onUpload).not.toHaveBeenCalled()
  })
})

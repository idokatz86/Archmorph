import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import UploadStep from '../../DiagramTranslator/UploadStep'

describe('UploadStep', () => {
  const originalPdfViewerEnabled = navigator.pdfViewerEnabled

  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:pdf-preview')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    Object.defineProperty(navigator, 'pdfViewerEnabled', { configurable: true, value: originalPdfViewerEnabled })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Object.defineProperty(navigator, 'pdfViewerEnabled', { configurable: true, value: originalPdfViewerEnabled })
  })

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

  it('shows Analyze button when file is selected', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('Analyze This Diagram')).toBeInTheDocument()
  })

  it('shows Remove button when file is selected', () => {
    const file = new File(['test'], 'diagram.png', { type: 'image/png' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    expect(screen.getByText('Remove')).toBeInTheDocument()
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

  it('shows first-page PDF preview with page count and file size metadata', async () => {
    const file = new File(['%PDF-1.7\n/Type /Page\n/Count 1'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)

    expect(await screen.findByText('PDF Preview')).toBeInTheDocument()
    expect(screen.getByLabelText('First page PDF preview')).toBeInTheDocument()
    expect(screen.getByText(/1 page ·/)).toBeInTheDocument()
  })

  it('supports keyboard focus for preview controls', async () => {
    const file = new File(['%PDF-1.7\n/Type /Page\n/Count 1'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)

    const openLarger = await screen.findByRole('button', { name: 'Open Larger View' })
    openLarger.focus()
    expect(openLarger).toHaveFocus()
    expect(screen.getByRole('group', { name: 'PDF zoom controls' })).toBeInTheDocument()
  })

  it('opens larger inspectable PDF view', async () => {
    const user = userEvent.setup()
    const file = new File(['%PDF-1.7\n/Type /Page\n/Count 1'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)

    await user.click(await screen.findByRole('button', { name: 'Open Larger View' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByLabelText('Large first page PDF preview')).toBeInTheDocument()
  })

  it('shows graceful fallback when inline PDF preview is unsupported', async () => {
    Object.defineProperty(navigator, 'pdfViewerEnabled', { configurable: true, value: false })
    const file = new File(['%PDF-1.7\n/Type /Page\n/Count 1'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)

    expect(await screen.findByText(/Inline PDF preview is not supported/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open PDF in a new tab' })).toBeInTheDocument()
  })

  it('shows encrypted PDF preview failure message', async () => {
    const encryptedFile = new File(['placeholder'], 'encrypted.pdf', { type: 'application/pdf' })
    Object.defineProperty(encryptedFile, 'arrayBuffer', {
      configurable: true,
      value: vi.fn(async () => new TextEncoder().encode('%PDF-1.7\n/Encrypt <<>>\n/Count 1').buffer),
    })
    render(<UploadStep {...defaultProps} selectedFile={encryptedFile} />)

    expect(await screen.findByText(/Preview unavailable: this PDF appears encrypted/)).toBeInTheDocument()
  })

  it('does not persist PDF preview bytes to sessionStorage by default', async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const file = new File(['%PDF-1.7\n/Type /Page\n/Count 1'], 'diagram.pdf', { type: 'application/pdf' })
    render(<UploadStep {...defaultProps} selectedFile={file} />)
    await screen.findByText('PDF Preview')

    const archmorphWrites = setItemSpy.mock.calls.filter(([key]) => String(key).includes('archmorph'))
    expect(archmorphWrites).toHaveLength(0)
  })

  it('adds mobile-safe bottom padding to avoid overlap with chat launcher', () => {
    render(<UploadStep {...defaultProps} />)
    const card = screen.getByText('Upload Architecture Diagram').closest('.bg-primary')
    expect(card).toHaveClass('pb-24')
  })
})

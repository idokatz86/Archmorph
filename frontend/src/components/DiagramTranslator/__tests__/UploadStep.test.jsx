import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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
})

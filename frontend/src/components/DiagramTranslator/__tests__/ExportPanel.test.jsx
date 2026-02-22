import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ExportPanel from '../../DiagramTranslator/ExportPanel'

describe('ExportPanel', () => {
  const defaultProps = {
    exportLoading: {},
    onExportDiagram: vi.fn(),
  }

  it('renders the export title', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('Export Architecture Diagram')).toBeInTheDocument()
  })

  it('shows subtitle', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText(/Download in your preferred format/)).toBeInTheDocument()
  })

  it('renders Excalidraw button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('Excalidraw')).toBeInTheDocument()
  })

  it('renders Draw.io button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('Draw.io')).toBeInTheDocument()
  })

  it('renders Visio button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('Visio')).toBeInTheDocument()
  })

  it('calls onExportDiagram with correct format', async () => {
    const user = userEvent.setup()
    render(<ExportPanel {...defaultProps} />)
    await user.click(screen.getByText('Excalidraw'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('excalidraw')
  })

  it('calls onExportDiagram with drawio format', async () => {
    const user = userEvent.setup()
    render(<ExportPanel {...defaultProps} />)
    await user.click(screen.getByText('Draw.io'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('drawio')
  })

  it('calls onExportDiagram with vsdx format', async () => {
    const user = userEvent.setup()
    render(<ExportPanel {...defaultProps} />)
    await user.click(screen.getByText('Visio'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('vsdx')
  })
})

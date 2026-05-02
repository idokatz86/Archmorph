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
    expect(screen.getByText('Export Architecture Package')).toBeInTheDocument()
  })

  it('shows subtitle', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText(/Download polished HTML\/SVG output/)).toBeInTheDocument()
  })

  it('renders HTML Package button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('HTML Package')).toBeInTheDocument()
  })

  it('renders Target SVG button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('Target SVG')).toBeInTheDocument()
  })

  it('renders DR SVG button', () => {
    render(<ExportPanel {...defaultProps} />)
    expect(screen.getByText('DR SVG')).toBeInTheDocument()
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
    await user.click(screen.getByText('HTML Package'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('architecture-package-html')
  })

  it('calls onExportDiagram with SVG package format', async () => {
    const user = userEvent.setup()
    render(<ExportPanel {...defaultProps} />)
    await user.click(screen.getByText('Target SVG'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('architecture-package-svg')
  })

  it('calls onExportDiagram with DR SVG package format', async () => {
    const user = userEvent.setup()
    render(<ExportPanel {...defaultProps} />)
    await user.click(screen.getByText('DR SVG'))
    expect(defaultProps.onExportDiagram).toHaveBeenCalledWith('architecture-package-svg-dr')
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

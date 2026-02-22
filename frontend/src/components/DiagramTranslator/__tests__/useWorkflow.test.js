import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import useWorkflow, { DEFAULT_CHAT_MESSAGE } from '../../DiagramTranslator/useWorkflow'

describe('useWorkflow', () => {
  it('returns initial state with step=upload', () => {
    const { result } = renderHook(() => useWorkflow())
    expect(result.current.state.step).toBe('upload')
  })

  it('has null diagramId initially', () => {
    const { result } = renderHook(() => useWorkflow())
    expect(result.current.state.diagramId).toBeNull()
  })

  it('has initial chat message', () => {
    const { result } = renderHook(() => useWorkflow())
    expect(result.current.state.iacChatMessages).toHaveLength(1)
    expect(result.current.state.iacChatMessages[0].role).toBe('assistant')
  })

  it('set() updates state', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.set({ step: 'analyzing' }) })
    expect(result.current.state.step).toBe('analyzing')
  })

  it('addProgress() appends to analyzeProgress', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.addProgress('Step 1') })
    act(() => { result.current.addProgress('Step 2') })
    expect(result.current.state.analyzeProgress).toEqual(['Step 1', 'Step 2'])
  })

  it('addChatMessage() appends to iacChatMessages', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.addChatMessage({ role: 'user', content: 'hello' }) })
    expect(result.current.state.iacChatMessages).toHaveLength(2)
    expect(result.current.state.iacChatMessages[1].content).toBe('hello')
  })

  it('updateAnswer() sets an answer', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.updateAnswer('q1', 'yes') })
    expect(result.current.state.answers.q1).toBe('yes')
  })

  it('setExportLoading() sets export loading state', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.setExportLoading('excalidraw', true) })
    expect(result.current.state.exportLoading.excalidraw).toBe(true)
  })

  it('setHldExportLoading() sets HLD export loading state', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.setHldExportLoading('pdf', true) })
    expect(result.current.state.hldExportLoading.pdf).toBe(true)
  })

  it('reset() returns to initial state', () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => {
      result.current.set({ step: 'results', diagramId: 'abc' })
      result.current.addProgress('test')
    })
    act(() => { result.current.reset() })
    expect(result.current.state.step).toBe('upload')
    expect(result.current.state.diagramId).toBeNull()
    expect(result.current.state.analyzeProgress).toEqual([])
  })

  it('copyWithFeedback() sets copy feedback temporarily', async () => {
    const { result } = renderHook(() => useWorkflow())
    act(() => { result.current.copyWithFeedback('text', 'key1') })
    expect(result.current.state.copyFeedback.key1).toBe(true)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('text')
  })

  it('DEFAULT_CHAT_MESSAGE has correct structure', () => {
    expect(DEFAULT_CHAT_MESSAGE.role).toBe('assistant')
    expect(DEFAULT_CHAT_MESSAGE.content).toContain('IaC Assistant')
  })
})

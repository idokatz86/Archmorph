import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { saveSession, loadSession, clearSession } from '../../services/sessionCache'

describe('sessionCache', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ── Basic operations ──

  it('saveSession stores data to sessionStorage', () => {
    saveSession('diagram-1', { services: 3 }, [{ id: 'q1' }], { q1: 'yes' })
    const raw = sessionStorage.getItem('archmorph_session')
    expect(raw).not.toBeNull()
    const data = JSON.parse(raw)
    expect(data.diagramId).toBe('diagram-1')
    expect(data.analysis.services).toBe(3)
  })

  it('loadSession returns saved data', () => {
    saveSession('diagram-1', { zones: [] }, [], {})
    const result = loadSession()
    expect(result).not.toBeNull()
    expect(result.diagramId).toBe('diagram-1')
    expect(result.analysis.zones).toEqual([])
  })

  it('loadSession returns null when nothing is stored', () => {
    expect(loadSession()).toBeNull()
  })

  it('clearSession removes stored data', () => {
    saveSession('d1', {}, [], {})
    clearSession()
    expect(loadSession()).toBeNull()
    expect(sessionStorage.getItem('archmorph_session')).toBeNull()
  })

  // ── TTL expiry ──

  it('loadSession returns null when cache is older than 2 hours', () => {
    saveSession('d1', { data: 'old' }, [], {})

    // Advance time by 2 hours + 1 second
    vi.advanceTimersByTime(2 * 60 * 60 * 1000 + 1000)

    const result = loadSession()
    expect(result).toBeNull()
    // Should also clean up sessionStorage
    expect(sessionStorage.getItem('archmorph_session')).toBeNull()
  })

  it('loadSession returns data when cache is under 2 hours old', () => {
    saveSession('d1', { data: 'fresh' }, [], {})

    // Advance time by 1 hour 59 minutes
    vi.advanceTimersByTime(1 * 60 * 60 * 1000 + 59 * 60 * 1000)

    const result = loadSession()
    expect(result).not.toBeNull()
    expect(result.analysis.data).toBe('fresh')
  })

  // ── Data integrity ──

  it('preserves questions and answers', () => {
    const questions = [
      { id: 'q1', text: 'Environment?', options: ['Dev', 'Prod'] },
      { id: 'q2', text: 'HA needed?', options: ['Yes', 'No'] },
    ]
    const answers = { q1: 'Prod', q2: 'Yes' }

    saveSession('d1', { zones: [] }, questions, answers)
    const result = loadSession()

    expect(result.questions).toEqual(questions)
    expect(result.answers).toEqual(answers)
  })

  it('stores timestamp for TTL checks', () => {
    const before = Date.now()
    saveSession('d1', {}, [], {})
    const result = loadSession()
    expect(result.ts).toBeGreaterThanOrEqual(before)
    expect(result.ts).toBeLessThanOrEqual(Date.now())
  })

  // ── Single session limitation ──

  it('only stores last session (overwrite behavior)', () => {
    saveSession('diagram-A', { id: 'A' }, [], {})
    saveSession('diagram-B', { id: 'B' }, [], {})

    const result = loadSession()
    expect(result.diagramId).toBe('diagram-B')
    // diagram-A is lost
  })

  // ── Error handling ──

  it('loadSession returns null on corrupt JSON', () => {
    sessionStorage.setItem('archmorph_session', 'not-valid-json{{{')
    expect(loadSession()).toBeNull()
  })

  it('saveSession handles sessionStorage errors gracefully', () => {
    const originalSetItem = sessionStorage.setItem
    sessionStorage.setItem = vi.fn(() => {
      throw new Error('QuotaExceeded')
    })

    // Should not throw
    expect(() => saveSession('d1', { big: 'data' }, [], {})).not.toThrow()

    sessionStorage.setItem = originalSetItem
  })

  it('clearSession handles missing key gracefully', () => {
    // Clearing when nothing exists should not throw
    expect(() => clearSession()).not.toThrow()
  })

  // ── Default parameter handling ──

  it('saveSession handles missing questions and answers', () => {
    saveSession('d1', { zones: [] })
    const result = loadSession()
    expect(result.questions).toEqual([])
    expect(result.answers).toEqual({})
  })

  // ── Edge cases ──

  it('handles large analysis payloads', () => {
    const largeAnalysis = {
      zones: Array.from({ length: 20 }, (_, i) => ({
        id: i,
        name: `Zone ${i}`,
        services: Array.from({ length: 10 }, (_, j) => ({
          aws: `Service-${i}-${j}`,
          azure: `Azure-Service-${i}-${j}`,
          confidence: 0.85,
        })),
      })),
      mappings: Array.from({ length: 200 }, (_, i) => ({
        source_service: `SVC-${i}`,
        azure_service: `AZURE-${i}`,
        confidence: 0.9,
      })),
    }

    saveSession('large-diagram', largeAnalysis, [], {})
    const result = loadSession()
    expect(result.analysis.zones.length).toBe(20)
    expect(result.analysis.mappings.length).toBe(200)
  })

  it('handles empty analysis object', () => {
    saveSession('empty-analysis', {}, [], {})
    const result = loadSession()
    expect(result.analysis).toEqual({})
  })
})

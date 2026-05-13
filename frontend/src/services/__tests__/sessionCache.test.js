import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { saveSession, loadSession, clearSession, cacheImage, loadCachedImage } from '../../services/sessionCache'

function saveSessionWithOptIn(diagramId, analysis, questions = [], answers = {}, extra = {}) {
  return saveSession(diagramId, analysis, questions, answers, { ...extra, persistSensitive: true })
}

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
    saveSessionWithOptIn('diagram-1', { services: 3 }, [{ id: 'q1' }], { q1: 'yes' })
    // Multi-tab support (#265): per-diagram key
    const raw = sessionStorage.getItem('archmorph_session_diagram-1')
    expect(raw).not.toBeNull()
    const data = JSON.parse(raw)
    expect(data.diagramId).toBe('diagram-1')
    expect(data.analysis.services).toBe(3)
  })

  it('loadSession returns saved data', () => {
    saveSessionWithOptIn('diagram-1', { zones: [] }, [], {})
    const result = loadSession()
    expect(result).not.toBeNull()
    expect(result.diagramId).toBe('diagram-1')
    expect(result.analysis.zones).toEqual([])
  })

  it('loadSession returns null when nothing is stored', () => {
    expect(loadSession()).toBeNull()
  })

  it('clearSession removes stored data', () => {
    saveSessionWithOptIn('d1', {}, [], {})
    clearSession()
    expect(loadSession()).toBeNull()
    expect(sessionStorage.getItem('archmorph_session_d1')).toBeNull()
  })

  // ── TTL expiry ──

  it('loadSession returns null when cache is older than 2 hours', () => {
    saveSessionWithOptIn('d1', { data: 'old' }, [], {})

    // Advance time by 2 hours + 1 second
    vi.advanceTimersByTime(2 * 60 * 60 * 1000 + 1000)

    const result = loadSession()
    expect(result).toBeNull()
    // Should also clean up sessionStorage
    expect(sessionStorage.getItem('archmorph_session_d1')).toBeNull()
  })

  it('loadSession returns data when cache is under 2 hours old', () => {
    saveSessionWithOptIn('d1', { data: 'fresh' }, [], {})

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

    saveSessionWithOptIn('d1', { zones: [] }, questions, answers)
    const result = loadSession()

    expect(result.questions).toEqual(questions)
    expect(result.answers).toEqual(answers)
  })

  it('preserves adaptive question assumptions', () => {
    const assumptions = [
      { id: 'env_target', question: 'Environment?', assumed_answer: 'Production' },
    ]
    const allQuestions = [{ id: 'env_target' }, { id: 'arch_ha' }]

    saveSessionWithOptIn('d1', { zones: [] }, [], {}, { allQuestions, questionAssumptions: assumptions })
    const result = loadSession()

    expect(result.allQuestions).toEqual(allQuestions)
    expect(result.questionAssumptions).toEqual(assumptions)
  })

  it('stores timestamp for TTL checks', () => {
    const before = Date.now()
    saveSessionWithOptIn('d1', {}, [], {})
    const result = loadSession()
    expect(result.ts).toBeGreaterThanOrEqual(before)
    expect(result.ts).toBeLessThanOrEqual(Date.now())
  })

  // ── Single session limitation ──

  it('only stores last session (overwrite behavior)', () => {
    saveSessionWithOptIn('diagram-A', { id: 'A' }, [], {})
    saveSessionWithOptIn('diagram-B', { id: 'B' }, [], {})

    const result = loadSession()
    expect(result.diagramId).toBe('diagram-B')
    // diagram-A is lost
  })

  // ── Error handling ──

  it('loadSession returns null on corrupt JSON', () => {
    // Corrupt data at a per-diagram key
    sessionStorage.setItem('archmorph_session_bad', 'not-valid-json{{{')
    sessionStorage.setItem('archmorph_active_diagram', 'bad')
    expect(loadSession()).toBeNull()
  })

  it('saveSession handles sessionStorage errors gracefully', () => {
    const originalSetItem = sessionStorage.setItem
    sessionStorage.setItem = vi.fn(() => {
      throw new Error('QuotaExceeded')
    })

    // Should not throw
    expect(() => saveSessionWithOptIn('d1', { big: 'data' }, [], {})).not.toThrow()

    sessionStorage.setItem = originalSetItem
  })

  it('clearSession handles missing key gracefully', () => {
    // Clearing when nothing exists should not throw
    expect(() => clearSession()).not.toThrow()
  })

  // ── Default parameter handling ──

  it('saveSession handles missing questions and answers', () => {
    saveSessionWithOptIn('d1', { zones: [] })
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

    saveSessionWithOptIn('large-diagram', largeAnalysis, [], {})
    const result = loadSession()
    expect(result.analysis.zones.length).toBe(20)
    expect(result.analysis.mappings.length).toBe(200)
  })

  it('handles empty analysis object', () => {
    saveSessionWithOptIn('empty-analysis', {}, [], {})
    const result = loadSession()
    expect(result.analysis).toEqual({})
  })

  it('does not persist sensitive analysis by default (confidential mode)', () => {
    saveSession('sensitive-diagram', { zones: ['private'] }, [], {}, { exportCapability: 'secret-token' })
    expect(sessionStorage.getItem('archmorph_session_sensitive-diagram')).toBeNull()
    expect(loadSession('sensitive-diagram')).toBeNull()
  })

  it('never persists exportCapability even with explicit sensitive cache opt-in', () => {
    saveSessionWithOptIn('demo-diagram', { zones: [] }, [], {}, { exportCapability: 'secret-token' })
    const raw = sessionStorage.getItem('archmorph_session_demo-diagram')
    expect(raw).not.toBeNull()
    const payload = JSON.parse(raw)
    expect(payload.exportCapability).toBeUndefined()
    expect(payload.analysis.export_capability).toBeUndefined()
  })

  it('does not persist uploaded image bytes by default (confidential mode)', () => {
    cacheImage('diagram-1', 'ZmFrZS1pbWFnZQ==', 'image/png')
    expect(sessionStorage.getItem('archmorph_img_diagram-1')).toBeNull()
  })

  it('clears legacy sensitive cache payloads instead of restoring them by default', () => {
    sessionStorage.setItem('archmorph_active_diagram', 'legacy-diagram')
    sessionStorage.setItem('archmorph_session_legacy-diagram', JSON.stringify({
      diagramId: 'legacy-diagram',
      analysis: { zones: ['private'], export_capability: 'nested-token' },
      exportCapability: 'top-level-token',
      questions: [],
      answers: {},
      ts: Date.now(),
    }))

    expect(loadSession()).toBeNull()
    expect(sessionStorage.getItem('archmorph_session_legacy-diagram')).toBeNull()
    expect(sessionStorage.getItem('archmorph_session')).toBeNull()
  })

  it('rewrites allowed legacy cache payloads after removing export capabilities', () => {
    sessionStorage.setItem('archmorph_sensitive_cache_opt_in', 'true')
    sessionStorage.setItem('archmorph_active_diagram', 'legacy-diagram')
    sessionStorage.setItem('archmorph_session_legacy-diagram', JSON.stringify({
      diagramId: 'legacy-diagram',
      analysis: { zones: ['private'], export_capability: 'nested-token' },
      exportCapability: 'top-level-token',
      questions: [],
      answers: {},
      ts: Date.now(),
    }))

    const restored = loadSession()
    expect(restored.analysis.export_capability).toBeUndefined()
    expect(restored.exportCapability).toBeUndefined()
    const rewritten = JSON.parse(sessionStorage.getItem('archmorph_session_legacy-diagram'))
    expect(rewritten.analysis.export_capability).toBeUndefined()
    expect(rewritten.exportCapability).toBeUndefined()
  })

  it('persists session and image data when storage opt-in is enabled', () => {
    sessionStorage.setItem('archmorph_sensitive_cache_opt_in', 'true')

    saveSession('opted-in-diagram', { zones: ['demo'] }, [], {})
    cacheImage('opted-in-diagram', 'ZmFrZS1pbWFnZQ==', 'image/png')

    expect(loadSession('opted-in-diagram').analysis.zones).toEqual(['demo'])
    expect(loadCachedImage('opted-in-diagram').contentType).toBe('image/png')
  })

  it('honors explicit false override even when storage opt-in is enabled', () => {
    sessionStorage.setItem('archmorph_sensitive_cache_opt_in', 'true')

    saveSession('blocked-diagram', { zones: ['private'] }, [], {}, { persistSensitive: false })
    cacheImage('blocked-diagram', 'ZmFrZS1pbWFnZQ==', 'image/png', { persistSensitive: false })

    expect(sessionStorage.getItem('archmorph_session_blocked-diagram')).toBeNull()
    expect(sessionStorage.getItem('archmorph_img_blocked-diagram')).toBeNull()
  })
})

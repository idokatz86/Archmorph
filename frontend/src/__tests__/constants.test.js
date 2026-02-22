import { describe, it, expect } from 'vitest'
import { API_BASE, APP_VERSION, CATEGORY_ICONS, getCategoryIcon } from '../constants'

describe('constants', () => {
  it('API_BASE defaults to /api', () => {
    expect(API_BASE).toBe('/api')
  })

  it('APP_VERSION is a semver string', () => {
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+$/)
  })

  it('CATEGORY_ICONS maps known categories to components', () => {
    expect(CATEGORY_ICONS).toHaveProperty('Compute')
    expect(CATEGORY_ICONS).toHaveProperty('Storage')
    expect(CATEGORY_ICONS).toHaveProperty('Networking')
    expect(CATEGORY_ICONS).toHaveProperty('Security')
    expect(CATEGORY_ICONS).toHaveProperty('default')
  })

  it('getCategoryIcon returns default icon for unknown category', () => {
    const icon = getCategoryIcon('UnknownStuff')
    expect(icon).toBe(CATEGORY_ICONS.default)
  })

  it('getCategoryIcon returns correct icon for known category', () => {
    expect(getCategoryIcon('Compute')).toBe(CATEGORY_ICONS.Compute)
    expect(getCategoryIcon('Security')).toBe(CATEGORY_ICONS.Security)
  })
})

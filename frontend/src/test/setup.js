import '@testing-library/jest-dom'
import { configure } from '@testing-library/react'
import Prism from 'prismjs'

// Increase waitFor timeout for CI environments (#375)
configure({ asyncUtilTimeout: 5000 })

// Make Prism available globally for language component plugins (prism-yaml, etc.)
global.Prism = Prism

const localStorageMock = (() => {
  let store = {}
  return {
    getItem: vi.fn((key) => (key in store ? store[key] : null)),
    setItem: vi.fn((key, value) => { store[key] = String(value) }),
    removeItem: vi.fn((key) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
    key: vi.fn((index) => Object.keys(store)[index] || null),
    get length() { return Object.keys(store).length },
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
  writable: true,
})
global.localStorage = localStorageMock

// Mock fetch globally with a safe default response
global.fetch = vi.fn().mockResolvedValue({
  ok: true,
  status: 200,
  json: () => Promise.resolve({}),
  text: () => Promise.resolve(''),
  headers: new Headers(),
  clone: function() { return this },
})

// Fail tests that trigger React error #31 ("Objects are not valid as a React child")
// or other critical React errors, while letting tests explicitly assert on errors
// they intentionally exercise (#912). Per-test overrides use vi.mocked(console.error).
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation((...args) => {
    const msg = typeof args[0] === 'string' ? args[0] : String(args[0] ?? '')
    // Throw for the specific React rendering crash we guard against (#31)
    if (msg.includes('Objects are not valid as a React child')) {
      throw new Error(`Unexpected React console error: ${msg}`)
    }
    // Suppress (but don't throw for) other React warnings to keep CI clean
    // without masking genuinely novel failures
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// Mock IntersectionObserver
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock clipboard
Object.defineProperty(navigator, 'clipboard', {
  writable: true,
  configurable: true,
  value: {
    writeText: vi.fn().mockResolvedValue(undefined),
    readText: vi.fn().mockResolvedValue(''),
  },
})

// Mock URL.createObjectURL / revokeObjectURL
global.URL.createObjectURL = vi.fn(() => 'blob:mock-url')
global.URL.revokeObjectURL = vi.fn()

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn()

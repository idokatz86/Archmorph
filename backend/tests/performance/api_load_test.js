import http from 'k6/http';
import { check, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

/**
 * Archmorph Load Test (Issues #290, #507)
 * 
 * Mixed traffic scenario matching production patterns:
 *   - 70% static/cached endpoints (health, services, flags, roadmap)
 *   - 20% cached LLM paths (chat with repeat queries)  
 *   - 10% uncached LLM paths (chat with unique queries)
 *
 * SLA targets from backend/performance_config.py:
 *   - p95 latency < 2000ms (fast endpoints), relaxed to 4000ms in CI
 *   - p99 latency < 5000ms, relaxed to 8000ms in CI
 *   - Error rate < 1% (5xx only)
 *   - Throughput: 100 RPS sustained (30 RPS in CI)
 *
 * CI environments auto-detect via CI/GITHUB_ACTIONS env vars and
 * scale load to 30% to account for single-core runner constraints.
 */

// Custom metrics
const errorRate = new Rate('errors');
const chatLatency = new Trend('chat_latency', true);
const catalogLatency = new Trend('catalog_latency', true);
const rateLimitRate = new Rate('rate_limited');

// CI environments (GitHub Actions) have limited CPU; scale load accordingly
const isCI = !!__ENV.CI || !!__ENV.GITHUB_ACTIONS;
const RATE_MULTIPLIER = isCI ? 0.3 : 1;  // 30 RPS in CI, 100 RPS locally

export const options = {
  scenarios: {
    // 70% — Static/cached endpoints
    static_traffic: {
      executor: 'constant-arrival-rate',
      rate: Math.ceil(70 * RATE_MULTIPLIER),
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: Math.ceil(35 * RATE_MULTIPLIER),
      maxVUs: Math.ceil(150 * RATE_MULTIPLIER),
      exec: 'staticEndpoints',
    },
    // 20% — Cached LLM (repeat queries hit cache)
    cached_llm: {
      executor: 'constant-arrival-rate',
      rate: Math.ceil(20 * RATE_MULTIPLIER),
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: Math.ceil(25 * RATE_MULTIPLIER),
      maxVUs: Math.ceil(80 * RATE_MULTIPLIER),
      exec: 'cachedLlmEndpoints',
    },
    // 10% — Uncached LLM (unique queries, full GPT round-trip)
    uncached_llm: {
      executor: 'constant-arrival-rate',
      rate: Math.ceil(10 * RATE_MULTIPLIER),
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: Math.ceil(15 * RATE_MULTIPLIER),
      maxVUs: Math.ceil(50 * RATE_MULTIPLIER),
      exec: 'uncachedLlmEndpoints',
    },
  },
  thresholds: {
    http_req_duration: [
      isCI ? 'p(95)<4000' : 'p(95)<2000',
      isCI ? 'p(99)<8000' : 'p(99)<5000',
    ],
    http_req_failed: ['rate<0.10'],
    errors: ['rate<0.01'],
    chat_latency: ['p(95)<5000'],
    catalog_latency: [isCI ? 'p(95)<3000' : 'p(95)<1500'],
  },
};

const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8000';
const API_KEY = __ENV.API_KEY || '';

const jsonHeaders = { 'Content-Type': 'application/json' };
if (API_KEY) {
  jsonHeaders['X-API-Key'] = API_KEY;
}

// Cached chat queries (will hit LLM cache after first call)
const CACHED_QUERIES = [
  'What is Archmorph?',
  'What cloud services does Archmorph support?',
  'How does the migration process work?',
];

export function staticEndpoints() {
  // Distribute across static endpoints
  const endpoints = [
    { path: '/api/health', name: 'health' },
    { path: '/api/services', name: 'services' },
    { path: '/api/flags', name: 'flags' },
    { path: '/api/roadmap', name: 'roadmap' },
    { path: '/api/versions', name: 'versions' },
  ];
  const ep = endpoints[__ITER % endpoints.length];

  const res = http.get(`${BASE_URL}${ep.path}`);
  const ok = check(res, {
    [`${ep.name}: no server error`]: (r) => r.status < 500,
    [`${ep.name}: latency < 2s`]: (r) => r.timings.duration < 2000,
  });
  if (ep.name === 'services') catalogLatency.add(res.timings.duration);
  rateLimitRate.add(res.status === 429);
  errorRate.add(res.status >= 500);
}

export function cachedLlmEndpoints() {
  const query = CACHED_QUERIES[__ITER % CACHED_QUERIES.length];
  const payload = JSON.stringify({
    session_id: `k6-cached-${__VU}`,
    message: query,
  });
  const res = http.post(`${BASE_URL}/api/chat`, payload, {
    headers: jsonHeaders,
    timeout: '10s',
  });
  check(res, {
    'cached-chat: no server error': (r) => r.status < 500,
  });
  chatLatency.add(res.timings.duration);
  rateLimitRate.add(res.status === 429);
  errorRate.add(res.status >= 500);
}

export function uncachedLlmEndpoints() {
  // Unique query per iteration to bypass cache
  const payload = JSON.stringify({
    session_id: `k6-uncached-${__VU}-${__ITER}`,
    message: `Explain the migration strategy for service-${__VU}-${__ITER} from AWS to Azure`,
  });
  const res = http.post(`${BASE_URL}/api/chat`, payload, {
    headers: jsonHeaders,
    timeout: '15s',
  });
  check(res, {
    'uncached-chat: no server error': (r) => r.status < 500,
  });
  chatLatency.add(res.timings.duration);
  rateLimitRate.add(res.status === 429);
  errorRate.add(res.status >= 500);
}

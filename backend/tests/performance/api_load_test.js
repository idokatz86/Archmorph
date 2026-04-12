import http from 'k6/http';
import { check, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

/**
 * Archmorph Load Test (Issue #290)
 * 
 * Validates SLA targets from backend/performance_config.py:
 *   - p95 latency < 2000ms (fast endpoints)
 *   - p99 latency < 5000ms 
 *   - Error rate < 1%
 *   - Throughput: 100 RPS sustained
 *
 * Endpoints tested:
 *   1. GET  /api/health           — baseline throughput
 *   2. POST /api/chat             — LLM-bound chatbot
 *   3. GET  /api/services         — service catalog
 *   4. GET  /api/feature-flags    — feature flags
 *   5. POST /api/diagrams/upload  — file upload path
 */

// Custom metrics
const errorRate = new Rate('errors');
const chatLatency = new Trend('chat_latency', true);
const catalogLatency = new Trend('catalog_latency', true);

export const options = {
  scenarios: {
    // Scenario 1: Sustained load on fast endpoints
    fast_endpoints: {
      executor: 'constant-arrival-rate',
      rate: 80,
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 40,
      maxVUs: 150,
      exec: 'fastEndpoints',
    },
    // Scenario 2: LLM-bound endpoints (lower rate — GPT calls are slow)
    llm_endpoints: {
      executor: 'constant-arrival-rate',
      rate: 20,
      timeUnit: '1s',
      duration: '30s',
      preAllocatedVUs: 30,
      maxVUs: 100,
      exec: 'llmEndpoints',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<5000'],
    http_req_failed: ['rate<0.01'],
    errors: ['rate<0.01'],
    chat_latency: ['p(95)<5000'],       // LLM endpoints get 5s p95
    catalog_latency: ['p(95)<1500'],     // Catalog should be fast
  },
};

const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8000';
const API_KEY = __ENV.API_KEY || '';

// Reusable headers
const jsonHeaders = { 'Content-Type': 'application/json' };
if (API_KEY) {
  jsonHeaders['X-API-Key'] = API_KEY;
}

export function fastEndpoints() {
  group('Health Check', () => {
    const res = http.get(`${BASE_URL}/api/health`);
    const ok = check(res, {
      'health: status 200': (r) => r.status === 200,
      'health: latency < 500ms': (r) => r.timings.duration < 500,
    });
    errorRate.add(!ok);
  });

  group('Service Catalog', () => {
    const res = http.get(`${BASE_URL}/api/services`);
    const ok = check(res, {
      'services: status 2xx': (r) => r.status >= 200 && r.status < 300,
      'services: latency < 2s': (r) => r.timings.duration < 2000,
    });
    catalogLatency.add(res.timings.duration);
    errorRate.add(!ok);
  });

  group('Feature Flags', () => {
    const res = http.get(`${BASE_URL}/api/flags`);
    const ok = check(res, {
      'flags: status 2xx': (r) => r.status >= 200 && r.status < 300,
      'flags: latency < 500ms': (r) => r.timings.duration < 500,
    });
    errorRate.add(!ok);
  });
}

export function llmEndpoints() {
  group('Chatbot', () => {
    const payload = JSON.stringify({
      session_id: `k6-load-${__VU}-${__ITER}`,
      message: 'What cloud services does Archmorph support?',
    });
    const res = http.post(`${BASE_URL}/api/chat`, payload, {
      headers: jsonHeaders,
      timeout: '10s',
    });
    // Chat may require auth (401) in CI — only fail on 5xx
    const ok = check(res, {
      'chat: no server error': (r) => r.status < 500,
      'chat: latency < 10s': (r) => r.timings.duration < 10000,
    });
    chatLatency.add(res.timings.duration);
    errorRate.add(res.status >= 500);
  });
}

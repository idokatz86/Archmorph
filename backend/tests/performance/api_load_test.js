import http from 'k6/http';
import { check } from 'k6';

/**
 * 🚨 PERFORMANCE MASTER DIRECTIVES 🚨
 * Goal: SLA Validations defined in `backend/performance_config.py`
 * - Target RPS: 100
 * - SLA Max Error Rate: < 1%
 * - SLA Latency: p95 < 1500ms, p99 < 5s (5000ms)
 */

export const options = {
  scenarios: {
    constant_request_rate: {
      executor: 'constant-arrival-rate',
      rate: 100,            // 100 iterations per second
      timeUnit: '1s',
      duration: '30s',      // Sustained load for 30s
      preAllocatedVUs: 50,  // Keep idle VUs ready to meet the arrival rate
      maxVUs: 200,          // Cap parallel connections 
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1500', 'p(99)<5000'], // Enforce percentile limits
    http_req_failed: ['rate<0.01'],                  // Errors must be less than 1%
  },
};

// Map base URL to Docker/Local defaults
const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8000';

export default function () {
  // Hit health endpoint to ensure raw system throughput isn't blocked by generic issues
  const res = http.get(`${BASE_URL}/api/health`);
  
  check(res, {
    'is status 200': (r) => r.status === 200,
    'latency is under 5000ms': (r) => r.timings.duration < 5000,
  });
}

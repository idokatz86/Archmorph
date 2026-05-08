import { API_BASE } from '../constants';
import { TOKEN_KEY } from '../stores/useAuthStore';

export function buildJobStreamUrl(jobId) {
  const url = new URL(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/stream`, window.location.origin);
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) url.searchParams.set('token', token);
  } catch {
    // Ignore storage access failures; SWA cookie auth still works with EventSource.
  }
  return url.toString();
}
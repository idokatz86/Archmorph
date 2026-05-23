const { app } = require('@azure/functions');

const DEFAULT_BACKEND_API_BASE = 'https://api.archmorphai.com/api';
const UPSTREAM_TIMEOUT_MS = 5000;

function json(status, body) {
  return {
    status,
    jsonBody: body,
    headers: { 'Cache-Control': 'no-store' },
  };
}

async function readUpstreamPayload(upstream) {
  const contentType = upstream.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return upstream.json();
  }
  return { error: { message: await upstream.text() } };
}

app.http('swa-session', {
  methods: ['POST'],
  authLevel: 'anonymous',
  route: 'auth/swa-session',
  handler: async (request, context) => {
    const clientPrincipal = request.headers.get('x-ms-client-principal');
    if (!clientPrincipal) {
      return json(401, { error: { message: 'SWA authentication required' } });
    }

    const apiKey = process.env.ARCHMORPH_API_KEY;
    if (!apiKey) {
      context.error('ARCHMORPH_API_KEY is not configured for the SWA API bridge');
      return json(503, { error: { message: 'Authentication bridge is not configured' } });
    }

    const abortController = new AbortController();
    const timeout = setTimeout(() => abortController.abort(), UPSTREAM_TIMEOUT_MS);

    try {
      const apiBase = (process.env.ARCHMORPH_BACKEND_API_BASE || DEFAULT_BACKEND_API_BASE).replace(/\/$/, '');
      const upstream = await fetch(`${apiBase}/auth/swa-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({ client_principal: clientPrincipal }),
        signal: abortController.signal,
      });

      return json(upstream.status, await readUpstreamPayload(upstream));
    } catch (error) {
      const timedOut = error?.name === 'AbortError';
      context.error(`SWA auth bridge upstream ${timedOut ? 'timed out' : 'failed'}: ${error?.message || error}`);
      return json(timedOut ? 504 : 502, {
        error: {
          message: timedOut
            ? 'Authentication bridge timed out'
            : 'Authentication bridge could not reach the backend',
        },
      });
    } finally {
      clearTimeout(timeout);
    }
  },
});
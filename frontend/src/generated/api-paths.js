/**
 * API route constants and type-safe path helpers.
 * 
 * Generated from OpenAPI schema — do not edit manually.
 * Run: npm run generate:api-schema
 * 
 * @module generated/api-paths
 */

// ── Diagram Lifecycle ────────────────────────────────────────
export const API_DIAGRAMS = '/diagrams';
export const API_DIAGRAMS_UPLOAD = '/diagrams/upload';
export const API_DIAGRAM = (id) => `/diagrams/${id}`;
export const API_DIAGRAM_ANALYZE = (id) => `/diagrams/${id}/analyze`;
export const API_DIAGRAM_QUESTIONS = (id) => `/diagrams/${id}/questions`;
export const API_DIAGRAM_HLD = (id) => `/diagrams/${id}/hld`;
export const API_DIAGRAM_GENERATE_IAC = (id) => `/diagrams/${id}/generate`;
export const API_DIAGRAM_EXPORT = (id) => `/diagrams/${id}/export-hld`;
export const API_DIAGRAM_COST = (id) => `/diagrams/${id}/cost-estimate`;
export const API_DIAGRAM_PREVIEW = (id) => `/diagrams/${id}/terraform-preview`;

// ── Authentication ───────────────────────────────────────────
export const API_AUTH_ME = '/auth/me';
export const API_AUTH_LOGIN = '/auth/login';
export const API_AUTH_LOGOUT = '/auth/logout';
export const API_AUTH_REFRESH = '/auth/refresh';
export const API_AUTH_GITHUB = '/auth/github';

// ── Services & Catalog ───────────────────────────────────────
export const API_SERVICES = '/services';
export const API_SERVICES_STATS = '/services/stats';
export const API_SERVICES_PROVIDERS = '/services/providers';
export const API_SERVICES_CATEGORIES = '/services/categories';
export const API_SERVICES_MAPPINGS = '/services/mappings';

// ── Chat & AI ────────────────────────────────────────────────
export const API_CHAT = '/chat';
export const API_CHAT_HISTORY = (sessionId) => `/chat/history/${sessionId}`;

// ── Jobs (SSE streaming) ─────────────────────────────────────
export const API_JOBS = '/jobs';
export const API_JOB_STREAM = (jobId) => `/jobs/${jobId}/stream`;
export const API_JOB_STATUS = (jobId) => `/jobs/${jobId}`;

// ── Feature Flags ────────────────────────────────────────────
export const API_FLAGS = '/flags';
export const API_FLAG = (name) => `/flags/${name}`;

// ── Feedback ─────────────────────────────────────────────────
export const API_FEEDBACK = '/feedback';
export const API_FEEDBACK_NPS = '/feedback/nps';

// ── Analytics ────────────────────────────────────────────────
export const API_ANALYTICS_EVENTS = '/analytics/events';
export const API_ANALYTICS_FUNNEL = '/analytics/funnel';

// ── Reports & Sharing ────────────────────────────────────────
export const API_REPORTS = '/reports';
export const API_SHARES = '/shares';
export const API_SHARE = (shareId) => `/shares/${shareId}`;

// ── Versioning & Diff ────────────────────────────────────────
export const API_VERSIONING = '/versioning';
export const API_DIFF = '/diff';

// ── Admin ────────────────────────────────────────────────────
export const API_ADMIN = '/admin';
export const API_ADMIN_DASHBOARD = '/admin/dashboard';

// ── Health & System ──────────────────────────────────────────
export const API_HEALTH = '/health';
export const API_VERSIONS = '/versions';
export const API_CONTACT = '/contact';

// ── Legal ────────────────────────────────────────────────────
export const API_LEGAL_PRIVACY = '/legal/privacy';
export const API_LEGAL_TERMS = '/legal/terms';
export const API_LEGAL_COOKIES = '/legal/cookies';

// ── Roadmap ──────────────────────────────────────────────────
export const API_ROADMAP = '/roadmap';
export const API_ROADMAP_BUG_REPORT = '/roadmap/bug-report';

// ── Profile ──────────────────────────────────────────────────
export const API_PROFILE = '/profile';

// ── Samples ──────────────────────────────────────────────────
export const API_SAMPLES = '/samples';
export const API_SAMPLE = (id) => `/samples/${id}`;
export const API_SAMPLE_ANALYZE = (id) => `/samples/${id}/analyze`;

// ── Cost ─────────────────────────────────────────────────────
export const API_COST = '/cost';
export const API_COST_COMPARISON = '/cost-comparison';

// ── Terraform ────────────────────────────────────────────────
export const API_TERRAFORM = '/terraform';
export const API_TERRAFORM_IMPORT = '/terraform/import';

// ── Timeline ─────────────────────────────────────────────────
export const API_TIMELINE = '/timeline';

// ── Compliance ───────────────────────────────────────────────
export const API_COMPLIANCE = '/compliance';

// ── Network ──────────────────────────────────────────────────
export const API_NETWORK = '/network';

// ── SKU Translation ──────────────────────────────────────────
export const API_SKU = '/sku';

// ── Collaboration ────────────────────────────────────────────
export const API_COLLABORATION = '/collaboration';

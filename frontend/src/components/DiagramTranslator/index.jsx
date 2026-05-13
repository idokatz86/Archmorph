import React, { useRef, useCallback, useEffect, Suspense, lazy } from 'react';
import {
  Upload, ChevronRight, CheckCircle, XCircle, X, Trash2,
  Loader2, Eye, Clock, FileCode, FileText, DollarSign, Rocket, Layers3, GitMerge,
} from 'lucide-react';
import { Button, Card, ErrorCard, Tabs } from '../ui';
import { buildJobStreamUrl } from '../../utils/jobStreamUrl';
import api from '../../services/apiClient';
import { saveSession, loadSession, clearSession, updateSessionCache, cacheImage, loadCachedImage } from '../../services/sessionCache';
import useWorkflow from './useWorkflow';
import useSSE from '../../hooks/useSSE';
import useSessionExpiry from '../../hooks/useSessionExpiry';
import useBeforeUnload from '../../hooks/useBeforeUnload';
import useAppStore from '../../stores/useAppStore';
import { isFeatureEnabled } from '../../featureFlags';
const UploadStep = lazy(() => import('./UploadStep'));
const GuidedQuestions = lazy(() => import('./GuidedQuestions'));
const AnalysisResults = lazy(() => import('./AnalysisResults'));
const IaCViewer = lazy(() => import('./IaCViewer'));
const CostPanel = lazy(() => import('./CostPanel'));
const HLDTab = lazy(() => import('./HLDTab'));
const PricingTab = lazy(() => import('./PricingTab'));
const MigrationChat = lazy(() => import('./MigrationChat'));
const DeployPanel = lazy(() => import('./DeployPanel'));

const normalizeIacFormat = (format) => (format === 'bicep' ? 'bicep' : 'terraform');
const DEFAULT_PROJECT_ID = 'demo-project';

/* ── Wave 2: 3-Phase layout (#512) ──
 * Phase 1 — Input:        upload, analyzing, questions
 * Phase 2 — Analysis:     results (+ dependency graph, migration chat)
 * Phase 3 — Deliverables: tabbed (IaC, HLD, Pricing, Deploy)
 */
const PHASES = [
  { id: 'input', label: 'Input', steps: ['upload', 'analyzing', 'questions'] },
  { id: 'analysis', label: 'Analysis', steps: ['results'] },
  { id: 'deliverables', label: 'Deliverables', steps: ['iac', 'hld', 'pricing', 'deploy'] },
];

function getPhase(stepId) {
  for (const p of PHASES) { if (p.steps.includes(stepId)) return p.id; }
  return 'input';
}

const DELIVERABLE_TABS = [
  { id: 'iac', label: 'IaC Code', icon: FileCode },
  { id: 'hld', label: 'HLD Document', icon: FileText },
  { id: 'pricing', label: 'Pricing', icon: DollarSign },
  { id: 'deploy', label: 'Deploy', icon: Rocket, feature: 'deployEngine' },
].filter(tab => !tab.feature || isFeatureEnabled(tab.feature));

const SPINE_STEPS = [
  { id: 'input', label: 'Input' },
  { id: 'analysis', label: 'Analysis' },
  { id: 'decisions', label: 'Decisions' },
  { id: 'deliverables', label: 'Deliverables' },
  { id: 'share', label: 'Share/Export' },
];

const STATUS_STYLES = {
  ready: 'border-cta/30 bg-cta/10 text-cta',
  generating: 'border-info/30 bg-info/10 text-info',
  failed: 'border-danger/30 bg-danger/10 text-danger',
  stale: 'border-warning/30 bg-warning/10 text-warning',
  needsReview: 'border-warning/30 bg-warning/10 text-warning',
  notGenerated: 'border-border bg-secondary text-text-muted',
};

function StatusPill({ status, label }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${STATUS_STYLES[status] || STATUS_STYLES.notGenerated}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {label}
    </span>
  );
}

function getWorkbenchSpine(state) {
  const hasQuestions = (state.questions || []).length > 0 || (state.questionAssumptions || []).length > 0;
  const inputFailed = state.step === 'upload' && !!state.error;
  const analysisFailed = ['analyzing', 'results'].includes(state.step) && !!state.error;
  const deliverablesGenerating = state.generatingIac || state.hldLoading || state.costBreakdownLoading;
  const deliverablesFailed = ['iac', 'hld', 'pricing', 'deploy'].includes(state.step) && !!state.error;
  return [
    { id: 'input', status: inputFailed ? 'failed' : state.selectedFile || state.analysis ? 'ready' : 'notGenerated', label: inputFailed ? 'Failed' : state.analysis ? 'Ready' : state.selectedFile ? 'Selected' : 'Awaiting input' },
    { id: 'analysis', status: analysisFailed ? 'failed' : state.step === 'analyzing' ? 'generating' : state.analysis ? 'ready' : 'notGenerated', label: analysisFailed ? 'Failed' : state.step === 'analyzing' ? 'Analyzing' : state.analysis ? 'Ready' : 'Not started' },
    { id: 'decisions', status: hasQuestions && state.step === 'questions' ? 'needsReview' : hasQuestions ? 'ready' : state.analysis ? 'notGenerated' : 'notGenerated', label: hasQuestions && state.step === 'questions' ? 'Needs review' : hasQuestions ? 'Captured' : 'Not started' },
    { id: 'deliverables', status: deliverablesFailed ? 'failed' : deliverablesGenerating ? 'generating' : state.iacCode ? 'ready' : 'notGenerated', label: deliverablesFailed ? 'Failed' : deliverablesGenerating ? 'Generating' : state.iacCode ? 'Ready' : 'Not generated' },
    { id: 'share', status: state.exportCapability ? 'ready' : state.iacCode ? 'needsReview' : 'notGenerated', label: state.exportCapability ? 'Ready' : state.iacCode ? 'Needs review' : 'Not generated' },
  ];
}

function getDeliverableStatuses(state) {
  return [
    { id: 'iac', label: 'IaC', status: state.generatingIac ? 'generating' : state.iacCode ? 'ready' : state.error && state.step === 'iac' ? 'failed' : 'notGenerated', text: state.generatingIac ? 'Generating' : state.iacCode ? 'Ready' : state.error && state.step === 'iac' ? 'Failed' : 'Not generated' },
    { id: 'hld', label: 'HLD', status: state.hldLoading ? 'generating' : state.hldData ? 'ready' : state.error && state.step === 'hld' ? 'failed' : 'notGenerated', text: state.hldLoading ? 'Generating' : state.hldData ? 'Ready' : state.error && state.step === 'hld' ? 'Failed' : 'Not generated' },
    { id: 'pricing', label: 'Cost', status: state.costBreakdownLoading ? 'generating' : state.costBreakdown ? 'ready' : 'notGenerated', text: state.costBreakdownLoading ? 'Generating' : state.costBreakdown ? 'Ready' : 'Not generated' },
    { id: 'package', label: 'Package', status: state.exportCapability ? 'ready' : state.iacCode ? 'needsReview' : 'notGenerated', text: state.exportCapability ? 'Ready' : state.iacCode ? 'Needs review' : 'Not generated' },
  ];
}

function WorkbenchSpineHeader({ state }) {
  const statusByStep = new Map(getWorkbenchSpine(state).map(item => [item.id, item]));
  return (
    <Card className="p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 id="workbench-spine-title" className="text-xl font-bold text-text-primary">Translation Workbench</h1>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-5 lg:min-w-[42rem]" role="group" aria-labelledby="workbench-spine-title">
          {SPINE_STEPS.map(step => {
            const stateForStep = statusByStep.get(step.id);
            return (
              <div key={step.id} className="min-w-0 rounded-lg border border-border bg-secondary/40 p-2">
                <div className="truncate text-xs font-semibold text-text-secondary">{step.label}</div>
                <div className="mt-1">
                  <StatusPill status={stateForStep.status} label={stateForStep.label} />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function DeliverablesHubHeader({ state }) {
  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 id="deliverables-hub-title" className="text-base font-semibold text-text-primary">Deliverables Hub</h2>
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby="deliverables-hub-title">
          {getDeliverableStatuses(state).map(item => (
            <StatusPill key={item.id} status={item.status} label={`${item.label}: ${item.text}`} />
          ))}
        </div>
      </div>
    </Card>
  );
}

function buildQuestionState(qData = {}) {
  const questions = qData.questions || [];
  const allQuestions = qData.all_questions || questions;
  const assumptions = qData.assumptions || [];
  const answers = {};

  allQuestions.forEach(q => {
    if (q.assumed_answer !== undefined) answers[q.id] = q.assumed_answer;
    else if (q.default !== undefined) answers[q.id] = q.default;
  });
  assumptions.forEach(a => {
    if (a.assumed_answer !== undefined) answers[a.id] = a.assumed_answer;
  });
  Object.assign(answers, qData.inferred_answers || {});

  return {
    questions,
    allQuestions,
    questionAssumptions: assumptions,
    answers,
    questionConstraints: qData.constraints || [],
    regionGroups: qData.region_groups || {},
  };
}

function ProjectPanel({ projectId, diagrams = [], combined, onAddDiagram, onViewCombined }) {
  if (!projectId || diagrams.length === 0) return null;
  const analyzedCount = diagrams.filter(d => d.status === 'analyzed').length;

  return (
    <Card className="p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Layers3 className="w-4 h-4 text-cta" aria-hidden="true" />
            <h2 className="text-sm font-semibold text-text-primary">Project Diagrams</h2>
            <span className="text-xs text-text-muted">{analyzedCount}/{diagrams.length} analyzed</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {diagrams.map(diagram => (
              <span key={diagram.diagram_id} className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-secondary px-2 py-1 text-xs text-text-secondary">
                <span className={`h-1.5 w-1.5 rounded-full ${diagram.status === 'analyzed' ? 'bg-cta' : 'bg-warning'}`} aria-hidden="true" />
                <span className="truncate max-w-[10rem]">{diagram.filename || diagram.diagram_id}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" icon={Upload} onClick={onAddDiagram}>Add Diagram</Button>
          <Button variant={combined ? 'primary' : 'secondary'} size="sm" icon={GitMerge} onClick={onViewCombined} disabled={analyzedCount === 0}>
            Combined Analysis
          </Button>
        </div>
      </div>
    </Card>
  );
}

export default function DiagramTranslator() {
  const {
    state, set, addProgress, addChatMessage,
    setExportLoading, setHldExportLoading,
    updateAnswer, reset, copyWithFeedback,
  } = useWorkflow();

  const fileInputRef = useRef(null);
  const iacChatEndRef = useRef(null);
  const iacChatInputRef = useRef(null);

  // Refs for cleanup of async resources
  const activeEsRef = useRef(null);        // current EventSource
  const activeIntervalRef = useRef(null);  // current setInterval
  const activeTimeoutsRef = useRef([]);    // pending setTimeout IDs
  const filePreviewUrlRef = useRef(null);  // latest blob URL
  const abortRef = useRef(null);           // AbortController for fetch calls

  // Session expiry warning countdown (#261) + auto-reset on expiry (#227)
  const handleSessionExpired = useCallback(() => {
    set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
    clearSession();
  }, [set]);
  const { expiryWarning, dismissWarning } = useSessionExpiry({
    diagramId: state.diagramId,
    onExpired: handleSessionExpired,
  });

  // Warn before closing tab if user has an active analysis (#312)
  useBeforeUnload(state.step !== 'upload' && state.diagramId);

  // Keep blob URL ref in sync
  useEffect(() => {
    filePreviewUrlRef.current = state.filePreviewUrl;
  }, [state.filePreviewUrl]);

  // ── Cleanup all async resources on unmount ──
  useEffect(() => {
    return () => {
      // Abort any in-flight fetch requests
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      // Close any active EventSource
      if (activeEsRef.current) {
        activeEsRef.current.close();
        activeEsRef.current = null;
      }
      // Clear any active interval
      if (activeIntervalRef.current) {
        clearInterval(activeIntervalRef.current);
        activeIntervalRef.current = null;
      }
      // Clear any pending timeouts
      activeTimeoutsRef.current.forEach(id => clearTimeout(id));
      activeTimeoutsRef.current = [];
      // Revoke blob URL
      if (filePreviewUrlRef.current) URL.revokeObjectURL(filePreviewUrlRef.current);
    };
  }, []);

  // ── Auto-restore session on mount (#269) ──
  useEffect(() => {
    const cached = loadSession();
    if (cached && cached.diagramId && cached.analysis) {
      set({
        diagramId: cached.diagramId,
        analysis: cached.analysis,
        questions: cached.questions || [],
        allQuestions: cached.allQuestions || cached.questions || [],
        questionAssumptions: cached.questionAssumptions || [],
        answers: cached.answers || {},
        iacCode: cached.iacCode || null,
        iacFormat: normalizeIacFormat(cached.iacFormat),
        hldData: cached.hldData || null,
        exportCapability: cached.exportCapability || cached.analysis?.export_capability || null,
        step: cached.iacCode ? 'iac' : 'results',
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Resume analysis from Dashboard (#517) ──
  const pendingResumeId = useAppStore(s => s.pendingResumeId);
  const setPendingResumeId = useAppStore(s => s.setPendingResumeId);
  const pendingTemplateAnalysis = useAppStore(s => s.pendingTemplateAnalysis);
  const setPendingTemplateAnalysis = useAppStore(s => s.setPendingTemplateAnalysis);
  useEffect(() => {
    if (!pendingResumeId) return;
    const resumeId = pendingResumeId;
    setPendingResumeId(null);
    (async () => {
      try {
        const data = await api.get(`/history/${resumeId}`);
        if (data && data.diagram_id) {
          set({
            diagramId: data.diagram_id,
            analysis: data.analysis || null,
            questions: data.questions || [],
            allQuestions: data.all_questions || data.questions || [],
            questionAssumptions: data.question_assumptions || [],
            answers: data.answers || {},
            iacCode: data.iac_code || null,
            iacFormat: normalizeIacFormat(data.iac_format),
            hldData: data.hld_data || null,
            step: data.iac_code ? 'iac' : data.analysis ? 'results' : 'upload',
          });
        }
      } catch {
        set({ error: 'Could not load saved analysis. It may have expired.' });
      }
    })();
  }, [pendingResumeId, setPendingResumeId, set]);

  // ── Load architecture template from Template Gallery (#244) ──
  useEffect(() => {
    if (!pendingTemplateAnalysis) return;
    const analysis = pendingTemplateAnalysis;
    setPendingTemplateAnalysis(null);
    reset();
    set({
      step: 'analyzing',
      diagramId: analysis.diagram_id,
      analysis,
      exportCapability: analysis.export_capability || null,
      analyzeProgress: [`Loading ${analysis.template_title || analysis.diagram_type} template...`],
    });
    (async () => {
      try {
        const qData = await api.post(`/diagrams/${analysis.diagram_id}/questions`);
        const questionState = buildQuestionState(qData);
        saveSession(analysis.diagram_id, analysis, questionState.questions, questionState.answers, {
          exportCapability: analysis.export_capability || null,
          allQuestions: questionState.allQuestions,
          questionAssumptions: questionState.questionAssumptions,
        });
        set({ ...questionState, step: 'results' });
      } catch {
        set({ step: 'results' });
      }
    })();
  }, [pendingTemplateAnalysis, setPendingTemplateAnalysis, reset, set]);

  // ── Auto-trigger HLD generation when entering HLD tab (#400) ──
  useEffect(() => {
    if (state.step === 'hld' && !state.hldData && !state.hldLoading && state.diagramId) {
      handleGenerateHld();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.step]);

  // ── Auto-fetch cost breakdown when entering Pricing tab (#401) ──
  useEffect(() => {
    if (state.step === 'pricing' && !state.costBreakdown && !state.costBreakdownLoading && state.diagramId) {
      set({ costBreakdownLoading: true });
      api.get(`/diagrams/${state.diagramId}/cost-breakdown`)
        .then(data => set({ costBreakdown: data, costBreakdownLoading: false }))
        .catch(() => set({ costBreakdownLoading: false }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.step]);

  // ── Drag & drop ──
  const refreshProjectStatus = useCallback(async (projectId) => {
    if (!projectId) return null;
    try {
      const project = await api.get(`/projects/${projectId}`);
      set({ projectId, projectStatus: project, projectDiagrams: project.diagrams || [] });
      return project;
    } catch {
      return null;
    }
  }, [set]);

  const handleViewCombinedAnalysis = async () => {
    if (!state.projectId) return;
    set({ loading: true, error: null });
    try {
      const combined = await api.get(`/projects/${state.projectId}/analysis`);
      set({ analysis: combined, step: 'results', loading: false, iacCode: null, diagramId: combined.diagram_id || state.diagramId });
      await refreshProjectStatus(state.projectId);
    } catch (err) {
      set({ error: err.message, loading: false });
    }
  };

  const handleAddProjectDiagram = () => {
    set({ step: 'upload', selectedFile: null, filePreviewUrl: null, iacCode: null, error: null, analysis: null });
  };

  const handlePurgeCurrentAnalysis = async () => {
    if (!state.diagramId) return;
    const confirmed = window.confirm(
      'Purge this analysis now? This deletes uploaded bytes and generated server-side artifacts for the current diagram.',
    );
    if (!confirmed) return;

    set({ loading: true, error: null });
    try {
      await api.delete(`/diagrams/${state.diagramId}/purge`);
      clearSession(state.diagramId);
      reset();
      if (state.projectId) await refreshProjectStatus(state.projectId);
    } catch (err) {
      set({
        loading: false,
        error: err.message || 'Purge failed. Please try again.',
      });
      return;
    }
    set({ loading: false });
  };

  // ── Session auto-recovery: push cached analysis back to backend on 404 ──
  const tryRestoreSession = async (diagramId) => {
    const cached = loadSession();
    if (!cached || cached.diagramId !== diagramId) return false;
    try {
      const payload = { analysis: cached.analysis };
      // Include HLD and IaC artefacts so export/download survives a backend restart
      if (cached.hldData?.hld) {
        payload.hld = cached.hldData.hld;
        payload.hld_markdown = cached.hldData.markdown || null;
      }
      if (cached.iacCode) {
        payload.iac_code = cached.iacCode;
        payload.iac_format = cached.iacFormat || null;
      }
      // Include cached diagram image so IMAGE_STORE is also restored (#333)
      const cachedImg = loadCachedImage(diagramId);
      if (cachedImg) {
        payload.image_base64 = cachedImg.base64;
        payload.image_content_type = cachedImg.contentType;
      }
      const restoredData = await api.post(`/diagrams/${diagramId}/restore-session`, payload);
      if (restoredData?.export_capability) {
        set({ exportCapability: restoredData.export_capability });
        updateSessionCache({ exportCapability: restoredData.export_capability });
      }
      return true;
    } catch {
      return false;
    }
  };

  /**
   * Execute an async action with automatic session-restore-and-retry on 404.
   * Collapses the duplicated try/restore/retry pattern used across handlers (#327).
   * @param {Function} action - async fn to execute (and retry after restore)
   * @param {Object} [opts] - { onExpired: fn, cleanup: fn }
   */
  const withRestore = async (action, opts = {}) => {
    try {
      return await action();
    } catch (err) {
      if (err.status === 404 && state.diagramId) {
        const restored = await tryRestoreSession(state.diagramId);
        if (restored) {
          try { return await action(); } catch { /* fall through */ }
        }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
        clearSession();
        if (opts.cleanup) opts.cleanup();
        return null;
      }
      throw err;
    }
  };

  // ── Drag & drop ──
  const handleDragOver = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: true }); }, [set]);
  const handleDragLeave = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: false }); }, [set]);
  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); set({ dragOver: false });
    const file = e.dataTransfer?.files?.[0];
    if (file && (file.type.startsWith('image/') || file.name.match(/\.(png|jpe?g|svg|pdf|vsdx|drawio)$/i))) {
      const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
      if (file.size > MAX_FILE_SIZE) {
        set({ error: 'File exceeds 10 MB limit. Please upload a smaller file.' });
        return;
      }
      if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
      set({
        selectedFile: file,
        filePreviewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
      });
    }
  }, [set, state.filePreviewUrl]);

  const handleFileSelect = useCallback((file) => {
    if (!file) return;
    const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
    if (file.size > MAX_FILE_SIZE) {
      set({ error: 'File exceeds 10 MB limit. Please upload a smaller file.' });
      return;
    }
    if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
    // Clear stale errors when user selects a new file (#227)
    set({
      selectedFile: file,
      filePreviewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
      error: null,
    });
  }, [set, state.filePreviewUrl]);

  // ── Upload & Analyze ──
  const handleUpload = async (file) => {
    set({ error: null, step: 'analyzing', analyzeProgress: [] });
    // Create a new AbortController for this upload flow
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    addProgress('Connecting to analysis engine...');

    try {
      const formData = new FormData();
      formData.append('file', file);

      addProgress('Uploading diagram...');
      const projectId = state.projectId || DEFAULT_PROJECT_ID;
      const uploadData = await api.post(`/projects/${projectId}/diagrams`, formData, signal);
      const { diagram_id } = uploadData;
      set({ projectId: uploadData.project_id || projectId, diagramId: diagram_id, exportCapability: uploadData.export_capability || null });
      await refreshProjectStatus(uploadData.project_id || projectId);

      // Cache uploaded image for session restore (#333)
      if (file.type.startsWith('image/') && file.size < 1_000_000) {
        const reader = new FileReader();
        reader.onload = () => {
          const b64 = reader.result.split(',')[1];
          cacheImage(diagram_id, b64, file.type);
        };
        reader.readAsDataURL(file);
      }

      addProgress('Starting architecture analysis...');

      // Try async endpoint with SSE for real-time progress
      let useAsyncEndpoint = true;
      let asyncData;
      try {
        asyncData = await api.post(`/diagrams/${diagram_id}/analyze-async`, undefined, signal);
        // apiClient throws on non-2xx, so if we get here it's ok
        // But we still need to check for 202-specific behavior; apiClient resolves JSON body
      } catch {
        useAsyncEndpoint = false;
      }

      if (useAsyncEndpoint) {
        // ── SSE real-time progress path ──
        const { job_id } = asyncData;
        set({ jobId: job_id });

        // Wait for SSE completion via a promise (with ref-tracked cleanup)
        const result = await new Promise((resolve, reject) => {
          const url = buildJobStreamUrl(job_id);
          const es = new EventSource(url);
          activeEsRef.current = es;

          const cleanup = () => {
            es.close();
            if (activeEsRef.current === es) activeEsRef.current = null;
          };

          es.addEventListener('progress', (e) => {
            try {
              const data = JSON.parse(e.data);
              if (data.message) addProgress(data.message);
            } catch { /* ignore */ }
          });

          es.addEventListener('complete', (e) => {
            try {
              const data = JSON.parse(e.data);
              cleanup();
              resolve(data.result ?? data);
            } catch (err) {
              cleanup();
              reject(err);
            }
          });

          es.addEventListener('error', (e) => {
            if (e.data) {
              try {
                const data = JSON.parse(e.data);
                cleanup();
                reject(new Error(data.error || data.message || 'Analysis failed'));
              } catch {
                cleanup();
                reject(new Error('Connection to analysis stream lost'));
              }
            } else {
              // Connection error — SSE spec fires generic error with no data
              cleanup();
              reject(new Error('Connection to analysis stream lost'));
            }
          });

          es.addEventListener('cancelled', () => {
            cleanup();
            reject(new Error('Analysis was cancelled'));
          });

          // Timeout safety net (5 minutes)
          const tid = setTimeout(() => { cleanup(); reject(new Error('Analysis timed out')); }, 300000);
          activeTimeoutsRef.current.push(tid);
        });

        // Handle non-architecture diagram
        if (result?.detail?.error === 'not_architecture_diagram') {
          const msg = result.detail.message || 'Not an architecture diagram.';
          const imageType = result.detail.classification?.image_type || 'unknown';
          set({
            error: `🚫 ${msg}\n\nDetected image type: "${imageType}". Please upload a cloud architecture diagram.`,
            step: 'upload',
          });
          return;
        }

        addProgress('Analysis complete. ✓');
        await new Promise(r => setTimeout(r, 400));

        set({ analysis: result, exportCapability: result.export_capability || state.exportCapability || null });
        await refreshProjectStatus(uploadData.project_id || projectId);
        const qData = await api.post(`/diagrams/${diagram_id}/questions`, undefined, signal);
        const questionState = buildQuestionState(qData);
        saveSession(diagram_id, result, questionState.questions, questionState.answers, {
          exportCapability: result.export_capability || uploadData.export_capability || null,
          allQuestions: questionState.allQuestions,
          questionAssumptions: questionState.questionAssumptions,
        });
        set({ ...questionState, step: 'results' });
      } else {
        // ── Fallback: sync endpoint with simulated progress ──
        addProgress('Analyzing architecture with GPT-4o Vision...');

        const waitingMessages = [
          'Scanning diagram components...',
          'Identifying cloud services and icons...',
          'Detecting networking topology...',
          'Analyzing compute and storage layers...',
          'Evaluating security boundaries...',
          'Mapping data flow connections...',
          'Reviewing architecture patterns...',
          'Cross-referencing service catalog...',
          'Validating service dependencies...',
          'Finalizing architecture analysis...',
        ];

        let msgIndex = 0;
        const progressInterval = setInterval(() => {
          if (msgIndex < waitingMessages.length) {
            addProgress(waitingMessages[msgIndex]);
            msgIndex++;
          }
        }, 2500 + Math.random() * 1500);
        activeIntervalRef.current = progressInterval;

        const result = await api.post(`/diagrams/${diagram_id}/analyze`, undefined, signal);
        clearInterval(progressInterval);
        if (activeIntervalRef.current === progressInterval) activeIntervalRef.current = null;

        // apiClient throws on non-2xx (including 422), so not_architecture_diagram
        // is caught in the catch block below.

        const provider = (result.source_provider || 'aws').toUpperCase();
        for (const zone of (result.zones || [])) {
          const svcNames = (zone.services || []).map(s => {
            if (typeof s === 'string') return s;
            return s.source || s.aws || s.gcp || s.source_service || s.name || '';
          }).filter(Boolean).slice(0, 3);
          const svcLabel = svcNames.length > 0 ? ` (${svcNames.join(', ')})` : '';
          addProgress(`Zone ${zone.number || zone.id}: ${zone.name}${svcLabel}...`);
          await new Promise(r => setTimeout(r, 200));
        }

        addProgress(`Mapping ${provider} services to Azure equivalents...`);
        addProgress('Analysis complete. ✓');
        await new Promise(r => setTimeout(r, 800));

        set({ analysis: result, exportCapability: result.export_capability || uploadData.export_capability || null });
        await refreshProjectStatus(uploadData.project_id || projectId);
        const qData = await api.post(`/diagrams/${diagram_id}/questions`, undefined, signal);
        const questionState = buildQuestionState(qData);
        saveSession(diagram_id, result, questionState.questions, questionState.answers, {
          exportCapability: result.export_capability || uploadData.export_capability || null,
          allQuestions: questionState.allQuestions,
          questionAssumptions: questionState.questionAssumptions,
        });
        set({ ...questionState, step: 'results' });
      }
    } catch (err) {
      // Handle not_architecture_diagram errors from apiClient
      if (err.status === 422 && err.body?.detail?.error === 'not_architecture_diagram') {
        const msg = err.body.detail.message || 'The uploaded image is not a valid architecture diagram.';
        const imageType = err.body.detail.classification?.image_type || 'unknown';
        set({
          error: `🚫 ${msg}\n\nDetected image type: "${imageType}". Please upload a cloud architecture diagram (AWS, GCP, or similar).`,
          step: 'upload',
        });
        return;
      }
      if ((err.status === 429 || err.status === 503) && err.body?.error?.details?.error === 'analysis_retryable') {
        const retryAfter = err.body.error.details.retry_after_seconds;
        const retryCopy = retryAfter ? ` Please retry in about ${retryAfter} seconds.` : ' Please retry shortly.';
        set({ error: `${err.body.error.message}${retryCopy}`, step: 'upload' });
        return;
      }
      if (err.name === 'AbortError') return; // Component unmounted
      set({ error: err.message, step: 'upload' });
    }
  };

  const handleLoadSample = async (sample) => {
    set({ step: 'analyzing', analyzeProgress: ['Loading sample diagram...'] });
    try {
      const result = await api.post(`/samples/${sample.id}/analyze`);
      set({ diagramId: result.diagram_id, analysis: result, exportCapability: result.export_capability || null });
      for (const zone of (result.zones || [])) {
        const svcNames = (zone.services || []).map(s => s.source || s.name || '').filter(Boolean).slice(0, 3);
        addProgress(`Zone ${zone.id}: ${zone.name} (${svcNames.join(', ')})...`);
        await new Promise(r => setTimeout(r, 300));
      }
      addProgress(`Mapping ${sample.provider.toUpperCase()} services to Azure equivalents...`);
      await new Promise(r => setTimeout(r, 400));
      addProgress('Sample loaded successfully \u2713');
      await new Promise(r => setTimeout(r, 600));
      const qData = await api.post(`/diagrams/${result.diagram_id}/questions`);
      const questionState = buildQuestionState(qData);
      saveSession(result.diagram_id, result, questionState.questions, questionState.answers, {
        exportCapability: result.export_capability || null,
        allQuestions: questionState.allQuestions,
        questionAssumptions: questionState.questionAssumptions,
      });
      set({ ...questionState, step: 'results' });
    } catch (err) {
      set({ error: 'Failed to load sample: ' + err.message, step: 'upload' });
    }
  };

  const handleApplyAnswers = async () => {
    set({ loading: true });
    try {
      const refined = await withRestore(
        () => api.post(`/diagrams/${state.diagramId}/apply-answers`, state.answers),
        { cleanup: () => set({ loading: false }) },
      );
      if (refined) {
        set({ analysis: { ...state.analysis, ...refined }, step: 'results' });
      }
    } catch (err) {
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleGenerateIac = async (fmt) => {
    set({ loading: true, iacFormat: fmt, generatingIac: true });
    try {
      const generationPath = state.analysis?.combined && state.projectId
        ? `/projects/${state.projectId}/generate?format=${fmt}`
        : `/diagrams/${state.diagramId}/generate?format=${fmt}`;
      const iacData = await withRestore(
        () => api.post(generationPath, undefined, undefined, 180_000),
        { cleanup: () => set({ loading: false, generatingIac: false }) },
      );
      if (iacData) {
        set({ iacCode: iacData.code, step: 'iac', generatingIac: false });
        updateSessionCache({ iacCode: iacData.code, iacFormat: fmt }); // #263
        // Fetch cost estimate in parallel (non-blocking)
        api.get(`/diagrams/${state.diagramId}/cost-estimate`).then(cost => {
          set({ costEstimate: cost });
        }).catch(() => {});
      }
    } catch (err) {
      set({ error: err.message, generatingIac: false });
    }
    set({ loading: false, generatingIac: false });
  };

  // Background parallel generation of both IaC + HLD (#task4)
  const handleGenerateAll = async (fmt) => {
    set({ loading: true, iacFormat: fmt, generatingIac: true, generatingAll: true, genProgress: 'Generating infrastructure code...' });
    try {
      const isCombinedProject = state.analysis?.combined && state.projectId;
      const generationPath = isCombinedProject
        ? `/projects/${state.projectId}/generate?format=${fmt}`
        : `/diagrams/${state.diagramId}/generate?format=${fmt}`;
      // Start IaC generation
      const iacData = await withRestore(
        () => api.post(generationPath, undefined, undefined, 180_000),
        { cleanup: () => set({ loading: false, generatingIac: false, generatingAll: false }) },
      );
      if (iacData) {
        if (isCombinedProject) {
          set({ iacCode: iacData.code, step: 'iac', generatingIac: false, generatingAll: false, genProgress: null });
          updateSessionCache({ iacCode: iacData.code, iacFormat: fmt });
          return;
        }
        set({ iacCode: iacData.code, genProgress: 'IaC complete. Generating HLD document...' });
        updateSessionCache({ iacCode: iacData.code, iacFormat: fmt });
        // Start HLD generation in parallel
        const [hldData, costData] = await Promise.allSettled([
          api.post(`/diagrams/${state.diagramId}/generate-hld`, undefined, undefined, 180_000),
          api.get(`/diagrams/${state.diagramId}/cost-estimate`),
        ]);
        if (hldData.status === 'fulfilled' && hldData.value?.hld) {
          set({ hldData: hldData.value });
          updateSessionCache({ hldData: hldData.value });
        }
        if (costData.status === 'fulfilled') {
          set({ costEstimate: costData.value });
        }
        set({ step: 'iac', generatingIac: false, generatingAll: false, genProgress: null });
      }
    } catch (err) {
      set({ error: err.message, generatingIac: false, generatingAll: false, genProgress: null });
    }
    set({ loading: false, generatingIac: false, generatingAll: false });
  };

  const handleHldExport = async (fmt) => {
    setHldExportLoading(fmt, true);
    try {
      // Include diagram image in HLD export if available (#357)
      const cachedImg = loadCachedImage(state.diagramId);
      const exportBody = {};
      if (cachedImg?.base64) {
        exportBody.diagram_image = cachedImg.base64;
      }
      const data = await withRestore(
        () => api.post(
          `/diagrams/${state.diagramId}/export-hld?format=${fmt}&include_diagrams=${state.hldIncludeDiagrams}&export_mode=customer`,
          exportBody,
          undefined,
          undefined,
          state.exportCapability ? { 'X-Export-Capability': state.exportCapability } : {},
        ),
        { cleanup: () => setHldExportLoading(fmt, false) },
      );
      if (data) {
        if (data.export_capability) {
          set({ exportCapability: data.export_capability });
          updateSessionCache({ exportCapability: data.export_capability });
        }
        const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: data.content_type });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename;
        a.click();
        URL.revokeObjectURL(url);
        copyWithFeedback('', `hld-${fmt}`);
      }
    } catch (err) {
      set({ error: `HLD export failed: ${err.message}` });
    }
    setHldExportLoading(fmt, false);
  };

  const handleExportDiagram = async (format) => {
    setExportLoading(format, true);
    try {
      const isArchitecturePackage = format.startsWith('architecture-package-');
      const packageSelection = format.replace('architecture-package-', '');
      const packageFormat = packageSelection.startsWith('svg') ? 'svg' : packageSelection;
      const packageDiagram = packageSelection === 'svg-dr' ? '&diagram=dr' : '';
      const data = await withRestore(
        () => isArchitecturePackage
          ? api.post(
              `/diagrams/${state.diagramId}/export-architecture-package?format=${packageFormat}${packageDiagram}`,
              undefined,
              undefined,
              undefined,
              state.exportCapability ? { 'X-Export-Capability': state.exportCapability } : {},
            )
          : api.post(
              `/diagrams/${state.diagramId}/export-diagram?format=${format}`,
              undefined,
              undefined,
              undefined,
              state.exportCapability ? { 'X-Export-Capability': state.exportCapability } : {},
            ),
        { cleanup: () => setExportLoading(format, false) },
      );
      if (data) {
        if (data.export_capability) {
          set({ exportCapability: data.export_capability });
          updateSessionCache({ exportCapability: data.export_capability });
        }
        const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
        const exportMime = isArchitecturePackage
          ? (packageFormat === 'html' ? 'text/html' : 'image/svg+xml')
          : format === 'excalidraw'
          ? 'application/json'
          : format === 'drawio'
          ? 'application/xml'
          : 'application/vnd.visio';
        const blob = new Blob([content], { type: exportMime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename || (isArchitecturePackage
          ? `archmorph-architecture-package${packageSelection === 'svg-dr' ? '-dr' : ''}.${packageFormat}`
          : `archmorph-diagram.${format === 'excalidraw' ? 'excalidraw' : format === 'drawio' ? 'drawio' : 'vdx'}`);
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      set({ error: `Export failed: ${err.message}` });
    }
    setExportLoading(format, false);
  };

  const handleIacChat = async () => {
    const text = state.iacChatInput.trim();
    if (!text || state.iacChatLoading) return;
    set({ iacChatInput: '' });
    addChatMessage({ role: 'user', content: text });
    set({ iacChatLoading: true });
    try {
      const data = await api.post(`/diagrams/${state.diagramId}/iac-chat`, {
        message: text, code: state.iacCode || '', format: state.iacFormat,
      }, undefined, 180_000);
      addChatMessage({
        role: 'assistant',
        content: data.reply || data.message || 'Done.',
        changes: data.changes_summary || [],
        services: data.services_added || [],
      });
      if (data.code && !data.error) {
        set({ previousIacCode: state.iacCode, iacCode: data.code });
        updateSessionCache({ iacCode: data.code });
      }
    } catch {
      addChatMessage({ role: 'assistant', content: 'Sorry, couldn\'t connect to the IaC assistant.' });
    }
    set({ iacChatLoading: false });
    setTimeout(() => iacChatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handlePushPr = async ({ repo, baseBranch, targetPath, githubToken }) => {
    const payload = {
      repo,
      iac_code: state.iacCode,
      iac_format: normalizeIacFormat(state.iacFormat),
      base_branch: baseBranch || 'main',
      target_path: targetPath || undefined,
      github_token: githubToken || undefined,
      analysis_summary: state.analysis || {},
      cost_estimate: state.costEstimate || state.costBreakdown || {},
    };
    return api.post('/integrations/github/push-pr', payload, undefined, 120_000);
  };

  const handleNotifyEmail = async (email) => {
    try {
      await api.post(`/diagrams/${state.diagramId}/notify-email`, {
        email,
        diagram_name: state.analysis?.diagram_type || '',
      });
      set({ notifyEmail: { sent: true, email } });
    } catch {
      set({ notifyEmail: { sent: true, email, failed: true } });
    }
  };

  const handleGenerateHld = async () => {
    set({ hldLoading: true, error: null });
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 180_000);
      activeTimeoutsRef.current.push(timeout);
      const data = await withRestore(
        () => api.post(`/diagrams/${state.diagramId}/generate-hld`, undefined, controller.signal, 180_000),
        { cleanup: () => set({ hldLoading: false }) },
      );
      clearTimeout(timeout);
      activeTimeoutsRef.current = activeTimeoutsRef.current.filter(id => id !== timeout);
      if (data?.hld) { set({ hldData: data }); updateSessionCache({ hldData: data }); } // #263
    } catch (err) {
      const msg = err.name === 'AbortError'
        ? 'HLD generation timed out. Please try again.'
        : 'HLD generation failed: ' + err.message;
      set({ error: msg });
    }
    set({ hldLoading: false });
  };

  const handleResetChat = () => {
    set({ iacChatMessages: [{ role: 'assistant', content: 'Chat reset. What would you like to change in your IaC code?' }] });
    if (state.diagramId) api.delete(`/diagrams/${state.diagramId}/iac-chat`).catch(() => {});
  };

  const handleOpenChatWithMessage = (msg) => {
    set({ iacChatOpen: true, iacChatInput: msg });
    setTimeout(() => iacChatInputRef.current?.focus(), 100);
  };

  const handleExportPackage = async () => {
    set({ exportingPackage: true });
    try {
      // Build a migration package ZIP with IaC + HLD + cost report
      const data = await api.post(`/diagrams/${state.diagramId}/export-package`, {
        iac_format: state.iacFormat,
        include_diagrams: state.hldIncludeDiagrams,
      });
      const b64 = data?.content_b64 || data?.data;
      if (b64) {
        const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename || 'archmorph-migration-package.zip';
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      set({ error: `Migration package export failed: ${err.message}` });
    }
    set({ exportingPackage: false });
  };

  // ── Render (#512 — 3-phase layout) ──
  const currentPhase = getPhase(state.step);
  const phaseIndex = PHASES.findIndex(p => p.id === currentPhase);

  // Deliverables tab state — when in deliverables phase, use step as active tab
  const activeDeliverable = PHASES[2].steps.includes(state.step) ? state.step : 'iac';

  // Build deliverable tabs with content
  const deliverableTabs = DELIVERABLE_TABS.map(tab => ({
    ...tab,
    content: (
      tab.id === 'iac' && state.iacCode ? (
        <IaCViewer
          iacCode={state.iacCode}
          previousIacCode={state.previousIacCode}
          iacFormat={state.iacFormat}
          copyFeedback={state.copyFeedback}
          iacChatOpen={state.iacChatOpen}
          iacChatMessages={state.iacChatMessages}
          iacChatInput={state.iacChatInput}
          iacChatLoading={state.iacChatLoading}
          iacChatEndRef={iacChatEndRef}
          iacChatInputRef={iacChatInputRef}
          onCopyWithFeedback={copyWithFeedback}
          onToggleChat={() => {
            set({ iacChatOpen: !state.iacChatOpen });
            setTimeout(() => iacChatInputRef.current?.focus(), 100);
          }}
          onOpenChatWithMessage={handleOpenChatWithMessage}
          onResetChat={handleResetChat}
          onSendChat={handleIacChat}
          onSetChatInput={(v) => set({ iacChatInput: v })}
          onPushPr={handlePushPr}
        />
      ) : tab.id === 'hld' ? (
        <HLDTab
          hldData={state.hldData}
          hldLoading={state.hldLoading}
          hldTab={state.hldTab}
          hldExportLoading={state.hldExportLoading}
          hldIncludeDiagrams={state.hldIncludeDiagrams}
          copyFeedback={state.copyFeedback}
          error={state.error}
          onGenerateHld={handleGenerateHld}
          onSetHldTab={(tab) => set({ hldTab: tab })}
          onSetHldIncludeDiagrams={(v) => set({ hldIncludeDiagrams: v })}
          onHldExport={handleHldExport}
          onCopyWithFeedback={copyWithFeedback}
          onSetStep={(step) => set({ step })}
        />
      ) : tab.id === 'pricing' ? (
        <PricingTab
          costBreakdown={state.costBreakdown}
          loading={state.costBreakdownLoading}
          onSetStep={(step) => set({ step })}
          onExportPackage={handleExportPackage}
          exportingPackage={state.exportingPackage}
        />
      ) : tab.id === 'deploy' ? (
        <DeployPanel isLoading={false} templateSource={state.iacCode} canvasState={state.analysis} />
      ) : null
    ),
  }));

  return (
    <div className="space-y-6">
      <WorkbenchSpineHeader state={state} />

      {/* Phase Bar (#512 — 3-phase progress) */}
      <div className="flex items-center justify-center gap-3 text-sm font-medium">
        {PHASES.map((phase, i) => {
          const isCurrent = phase.id === currentPhase;
          const isPast = i < phaseIndex;
          const isClickable = (phase.id === 'input') ||
            (phase.id === 'analysis' && !!state.analysis) ||
            (phase.id === 'deliverables' && !!state.iacCode);
          const firstStep = phase.steps[0];
          return (
            <React.Fragment key={phase.id}>
              <button
                type="button"
                onClick={() => isClickable && set({ step: firstStep })}
                disabled={!isClickable}
                className={`flex items-center gap-2 px-4 py-2 rounded-full transition-all duration-200 select-none ${
                  isCurrent
                    ? 'bg-cta/15 text-cta font-semibold'
                    : isPast
                      ? 'text-cta cursor-pointer hover:bg-cta/10'
                      : 'text-text-muted'
                } ${isClickable && !isCurrent ? 'cursor-pointer' : ''} ${!isClickable ? 'opacity-50 cursor-default' : ''}`}
              >
                {isPast ? (
                  <CheckCircle className="w-4 h-4" />
                ) : (
                  <span className={`w-6 h-6 rounded-full border-2 flex items-center justify-center text-xs font-bold ${isCurrent ? 'border-cta' : 'border-current'}`}>{i + 1}</span>
                )}
                <span className="hidden sm:inline">{phase.label}</span>
              </button>
              {i < PHASES.length - 1 && (
                <div className={`w-8 h-0.5 rounded-full transition-colors ${isPast ? 'bg-cta' : 'bg-border'}`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Error (#509 — structured error card) */}
      {state.error && (
        <ErrorCard
          title="Analysis Error"
          message={state.error}
          onRetry={() => { set({ error: null, step: 'upload' }); }}
          retryLabel="Re-upload Diagram"
        />
      )}

      {/* Session expiry warning (#261) */}
      {expiryWarning && (
        <Card className="p-3 border-warning/30 bg-warning/5" role="status" aria-live="polite">
          <div className="flex items-center gap-3">
            <Clock className="w-5 h-5 text-warning shrink-0" aria-hidden="true" />
            <p className="text-sm text-warning">{expiryWarning}</p>
            <button onClick={dismissWarning} className="ml-auto cursor-pointer hover:bg-secondary rounded-lg p-1 transition-colors" aria-label="Dismiss warning" title="Dismiss"><X className="w-4 h-4 text-text-muted" /></button>
          </div>
        </Card>
      )}

      {state.diagramId && (
        <Card className="p-3 border-danger/25 bg-danger/5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-text-secondary">
              Need to remove sensitive data now? Purge the current analysis to clear uploaded bytes, session analysis, project indexes, export capabilities, and queued jobs.
            </p>
            <Button
              variant="ghost"
              size="sm"
              icon={Trash2}
              onClick={handlePurgeCurrentAnalysis}
            >
              Purge Current Analysis
            </Button>
          </div>
        </Card>
      )}

      <ProjectPanel
        projectId={state.projectId}
        diagrams={state.projectDiagrams}
        combined={!!state.analysis?.combined}
        onAddDiagram={handleAddProjectDiagram}
        onViewCombined={handleViewCombinedAnalysis}
      />

      <Suspense fallback={<div className="flex items-center justify-center h-64"><Loader2 className="w-8 h-8 animate-spin text-cta" /></div>}>

      {/* ═══ Phase 1: Input (Upload + Analyzing + Questions) ═══ */}
      {state.step === 'upload' && (
        <UploadStep
          dragOver={state.dragOver}
          selectedFile={state.selectedFile}
          filePreviewUrl={state.filePreviewUrl}
          fileInputRef={fileInputRef}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onFileSelect={handleFileSelect}
          onUpload={handleUpload}
          onRemoveFile={() => {
            if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
            set({ selectedFile: null, filePreviewUrl: null });
          }}
          onLoadSample={handleLoadSample}
        />
      )}

      {state.step === 'analyzing' && (
        <Card className="p-8">
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center gap-3 mb-6">
              <Loader2 className="w-6 h-6 text-cta animate-spin" />
              <h2 className="text-xl font-bold text-text-primary">Analyzing Architecture...</h2>
            </div>
            <div className="space-y-1 font-mono text-xs">
              {state.analyzeProgress.map((msg, i) => (
                <div key={i} className="flex items-center gap-2 text-text-secondary animate-fade-in">
                  <CheckCircle className="w-3.5 h-3.5 text-cta shrink-0" />
                  <span>{msg}</span>
                </div>
              ))}
              <span className="inline-block w-1.5 h-4 bg-cta/60 animate-pulse ml-5" aria-hidden="true" />
            </div>
            <div className="mt-6 flex justify-end">
              <Button
                variant="ghost"
                icon={X}
                onClick={() => {
                  if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
                  if (activeEsRef.current) { activeEsRef.current.close(); activeEsRef.current = null; }
                  set({ step: 'upload', error: null, analyzeProgress: [] });
                }}
              >
                Cancel Analysis
              </Button>
            </div>
          </div>
        </Card>
      )}

      {state.step === 'questions' && (
        <GuidedQuestions
          analysis={state.analysis}
          questions={state.questions}
          allQuestions={state.allQuestions}
          assumptions={state.questionAssumptions}
          answers={state.answers}
          loading={state.loading}
          onUpdateAnswer={updateAnswer}
          onApplyAnswers={handleApplyAnswers}
          onSkip={() => {
            set({ step: 'results' });
          }}
          constraints={state.questionConstraints || []}
          regionGroups={state.regionGroups || {}}
        />
      )}

      {/* ═══ Phase 2: Analysis (Results + Migration Chat) ═══ */}
      {state.step === 'results' && state.analysis && (
        <AnalysisResults
          analysis={state.analysis}
          loading={state.loading}
          generatingIac={state.generatingIac}
          iacFormat={state.iacFormat}
          exportLoading={state.exportLoading}
          copyFeedback={state.copyFeedback}
          onSetStep={(step) => set({ step })}
          onReviewAssumptions={() => set({ step: 'questions' })}
          onGenerateIac={handleGenerateAll}
          genProgress={state.genProgress}
          notifyEmail={state.notifyEmail}
          onNotifyEmail={handleNotifyEmail}
          onExportDiagram={handleExportDiagram}
          onCopyWithFeedback={copyWithFeedback}
          diagramId={state.diagramId}
          exportCapability={state.exportCapability}
          assumptions={state.questionAssumptions}
          questionsCount={(state.questions || []).length}
          onExportCapability={(token) => {
            set({ exportCapability: token });
            updateSessionCache({ exportCapability: token });
          }}
        />
      )}

      {/* Migration Q&A Chat — visible on Analysis + Deliverables phases (#258) */}
      {state.diagramId && state.analysis && !state.analysis.combined && ['results', 'iac', 'hld'].includes(state.step) && (
        <MigrationChat diagramId={state.diagramId} />
      )}

      {/* ═══ Phase 3: Deliverables (Tabbed — IaC | HLD | Pricing | Deploy) ═══ */}
      {PHASES[2].steps.includes(state.step) && state.iacCode && (
        <div className="space-y-4">
          <DeliverablesHubHeader state={state} />
          <div className="flex items-center justify-between">
            <Button onClick={() => set({ step: 'results' })} variant="ghost" size="sm" icon={Eye}>Back to Analysis</Button>
          </div>
          <Tabs
            tabs={deliverableTabs}
            activeTab={activeDeliverable}
            onChange={(tabId) => {
              set({ step: tabId });
            }}
          />
        </div>
      )}

      </Suspense>
    </div>
  );
}

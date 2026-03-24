import React, { useRef, useCallback, useEffect, Suspense, lazy } from 'react';
import {
  Upload, ChevronRight, CheckCircle, XCircle, X,
  Loader2, Eye, Clock, FileCode, FileText, DollarSign, Rocket,
} from 'lucide-react';
import { Button, Card, ErrorCard, Tabs } from '../ui';
import { API_BASE } from '../../constants';
import api from '../../services/apiClient';
import { saveSession, loadSession, clearSession, updateSessionCache, cacheImage, loadCachedImage } from '../../services/sessionCache';
import useWorkflow from './useWorkflow';
import useSSE from '../../hooks/useSSE';
import useSessionExpiry from '../../hooks/useSessionExpiry';
import useBeforeUnload from '../../hooks/useBeforeUnload';

const UploadStep = lazy(() => import('./UploadStep'));
const GuidedQuestions = lazy(() => import('./GuidedQuestions'));
const AnalysisResults = lazy(() => import('./AnalysisResults'));
const IaCViewer = lazy(() => import('./IaCViewer'));
const CostPanel = lazy(() => import('./CostPanel'));
const HLDTab = lazy(() => import('./HLDTab'));
const PricingTab = lazy(() => import('./PricingTab'));
const MigrationChat = lazy(() => import('./MigrationChat'));
const DeployPanel = lazy(() => import('./DeployPanel'));

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
  { id: 'deploy', label: 'Deploy', icon: Rocket },
];

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
        answers: cached.answers || {},
        iacCode: cached.iacCode || null,
        iacFormat: cached.iacFormat || 'terraform',
        hldData: cached.hldData || null,
        step: cached.iacCode ? 'iac' : 'results',
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      await api.post(`/diagrams/${diagramId}/restore-session`, payload);
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
      const uploadData = await api.post('/projects/demo-project/diagrams', formData, signal);
      const { diagram_id } = uploadData;
      set({ diagramId: diagram_id });

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
          const url = `${API_BASE}/jobs/${job_id}/stream`;
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

        set({ analysis: result });

        const qData = await api.post(`/diagrams/${diagram_id}/questions`, undefined, signal);
        const questions = qData.questions || [];
        const defaults = {};
        questions.forEach(q => { defaults[q.id] = q.default; });
        saveSession(diagram_id, result, questions, defaults);
        set({ questions, answers: defaults, step: 'questions', questionConstraints: qData.constraints || [], regionGroups: qData.region_groups || {} });
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

        set({ analysis: result });

        const qData = await api.post(`/diagrams/${diagram_id}/questions`, undefined, signal);
        const questions = qData.questions || [];
        const defaults = {};
        questions.forEach(q => { defaults[q.id] = q.default; });
        saveSession(diagram_id, result, questions, defaults);
        set({ questions, answers: defaults, step: 'questions', questionConstraints: qData.constraints || [], regionGroups: qData.region_groups || {} });
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
      if (err.name === 'AbortError') return; // Component unmounted
      set({ error: err.message, step: 'upload' });
    }
  };

  const handleLoadSample = async (sample) => {
    set({ step: 'analyzing', analyzeProgress: ['Loading sample diagram...'] });
    try {
      const result = await api.post(`/samples/${sample.id}/analyze`);
      set({ diagramId: result.diagram_id, analysis: result });
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
      const questions = qData.questions || [];
      const defaults = {};
      questions.forEach(q => { defaults[q.id] = q.default; });
      saveSession(result.diagram_id, result, questions, defaults);
      set({ questions, answers: defaults, step: 'questions', questionConstraints: qData.constraints || [], regionGroups: qData.region_groups || {} });
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
      if (refined) set({ analysis: { ...state.analysis, ...refined }, step: 'results' });
    } catch (err) {
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleGenerateIac = async (fmt) => {
    set({ loading: true, iacFormat: fmt, generatingIac: true });
    try {
      const iacData = await withRestore(
        () => api.post(`/diagrams/${state.diagramId}/generate?format=${fmt}`, undefined, undefined, 180_000),
        { cleanup: () => set({ loading: false, generatingIac: false }) },
      );
      if (iacData) {
        set({ iacCode: iacData.code, step: 'iac', generatingIac: false });
        updateSessionCache({ iacCode: iacData.code, iacFormat: fmt }); // #263
        // Fetch cost estimate in parallel (non-blocking)
        api.get(`/diagrams/${state.diagramId}/cost-estimate`).then(cost => set({ costEstimate: cost })).catch(() => {});
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
      // Start IaC generation
      const iacData = await withRestore(
        () => api.post(`/diagrams/${state.diagramId}/generate?format=${fmt}`, undefined, undefined, 180_000),
        { cleanup: () => set({ loading: false, generatingIac: false, generatingAll: false }) },
      );
      if (iacData) {
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
        if (costData.status === 'fulfilled') set({ costEstimate: costData.value });
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
        () => api.post(`/diagrams/${state.diagramId}/export-hld?format=${fmt}&include_diagrams=${state.hldIncludeDiagrams}&export_mode=customer`, exportBody),
        { cleanup: () => setHldExportLoading(fmt, false) },
      );
      if (data) {
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
      const data = await withRestore(
        () => api.post(`/diagrams/${state.diagramId}/export-diagram?format=${format}`),
        { cleanup: () => setExportLoading(format, false) },
      );
      if (data) {
        const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
        const blob = new Blob([content], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename || `archmorph-diagram.${format === 'excalidraw' ? 'excalidraw' : format === 'drawio' ? 'drawio' : 'vdx'}`;
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
      : false,
  }));

  return (
    <div className="space-y-6">
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
          answers={state.answers}
          loading={state.loading}
          onUpdateAnswer={updateAnswer}
          onApplyAnswers={handleApplyAnswers}
          onSkip={() => set({ step: 'results' })}
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
          onGenerateIac={handleGenerateAll}
          genProgress={state.genProgress}
          notifyEmail={state.notifyEmail}
          onNotifyEmail={handleNotifyEmail}
          onExportDiagram={handleExportDiagram}
          onCopyWithFeedback={copyWithFeedback}
          diagramId={state.diagramId}
        />
      )}

      {/* Migration Q&A Chat — visible on Analysis + Deliverables phases (#258) */}
      {state.diagramId && state.analysis && ['results', 'iac', 'hld'].includes(state.step) && (
        <MigrationChat diagramId={state.diagramId} />
      )}

      {/* ═══ Phase 3: Deliverables (Tabbed — IaC | HLD | Pricing | Deploy) ═══ */}
      {PHASES[2].steps.includes(state.step) && state.iacCode && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Button onClick={() => set({ step: 'results' })} variant="ghost" size="sm" icon={Eye}>Back to Analysis</Button>
          </div>
          <Tabs
            tabs={deliverableTabs}
            activeTab={activeDeliverable}
            onChange={(tabId) => set({ step: tabId })}
          />
        </div>
      )}

      </Suspense>
    </div>
  );
}

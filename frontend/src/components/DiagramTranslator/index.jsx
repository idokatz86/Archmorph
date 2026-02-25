import React, { useRef, useCallback, useEffect } from 'react';
import {
  Upload, ChevronRight, CheckCircle, XCircle, X,
  Loader2, Eye,
} from 'lucide-react';
import { Button, Card } from '../ui';
import { API_BASE } from '../../constants';
import api from '../../services/apiClient';
import { saveSession, loadSession, clearSession } from '../../services/sessionCache';
import useWorkflow from './useWorkflow';
import useSSE from '../../hooks/useSSE';
import UploadStep from './UploadStep';
import GuidedQuestions from './GuidedQuestions';
import AnalysisResults from './AnalysisResults';
import IaCViewer from './IaCViewer';
// CostPanel hidden during beta — no money-related UI
// import CostPanel from './CostPanel';

const STEPS = [
  { id: 'upload', label: 'Upload', canNav: true },
  { id: 'analyzing', label: 'Analyzing', canNav: false },
  { id: 'questions', label: 'Customize' },
  { id: 'results', label: 'Results' },
  { id: 'iac', label: 'IaC Code' },
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

  // ── Drag & drop ──
  // ── Session auto-recovery: push cached analysis back to backend on 404 ──
  const tryRestoreSession = async (diagramId) => {
    const cached = loadSession();
    if (!cached || cached.diagramId !== diagramId) return false;
    try {
      await api.post(`/diagrams/${diagramId}/restore-session`, { analysis: cached.analysis });
      return true;
    } catch {
      return false;
    }
  };

  // ── Drag & drop ──
  const handleDragOver = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: true }); }, [set]);
  const handleDragLeave = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: false }); }, [set]);
  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); set({ dragOver: false });
    const file = e.dataTransfer?.files?.[0];
    if (file && (file.type.startsWith('image/') || file.name.match(/\.(svg|pdf|vsdx)$/i))) {
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
    set({
      selectedFile: file,
      filePreviewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
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
      const refined = await api.post(`/diagrams/${state.diagramId}/apply-answers`, state.answers);
      set({ analysis: { ...state.analysis, ...refined }, step: 'results' });
    } catch (err) {
      if (err.status === 404) {
        const restored = await tryRestoreSession(state.diagramId);
        if (restored) {
          try {
            const refined = await api.post(`/diagrams/${state.diagramId}/apply-answers`, state.answers);
            set({ analysis: { ...state.analysis, ...refined }, step: 'results', loading: false });
            return;
          } catch { /* fall through to error */ }
        }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload', loading: false });
        clearSession();
        return;
      }
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleGenerateIac = async (fmt) => {
    set({ loading: true, iacFormat: fmt });
    try {
      const iacData = await api.post(`/diagrams/${state.diagramId}/generate?format=${fmt}`);
      set({ iacCode: iacData.code, costEstimate: null, step: 'iac' });
    } catch (err) {
      if (err.status === 404) {
        const restored = await tryRestoreSession(state.diagramId);
        if (restored) {
          try {
            const iacData = await api.post(`/diagrams/${state.diagramId}/generate?format=${fmt}`);
            set({ iacCode: iacData.code, costEstimate: null, step: 'iac', loading: false });
            return;
          } catch { /* fall through */ }
        }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload', loading: false });
        clearSession();
        return;
      }
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleHldExport = async (fmt) => {
    setHldExportLoading(fmt, true);
    try {
      const data = await api.post(`/diagrams/${state.diagramId}/export-hld?format=${fmt}&include_diagrams=${state.hldIncludeDiagrams}`, {});
      const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: data.content_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = data.filename;
      a.click();
      URL.revokeObjectURL(url);
      copyWithFeedback('', `hld-${fmt}`);
    } catch (err) {
      if (err.status === 404) {
        const restored = await tryRestoreSession(state.diagramId);
        if (!restored) {
          set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
          clearSession();
          setHldExportLoading(fmt, false);
          return;
        }
        // Retry after restore
        try {
          const data = await api.post(`/diagrams/${state.diagramId}/export-hld?format=${fmt}&include_diagrams=${state.hldIncludeDiagrams}`, {});
          const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
          const blob = new Blob([bytes], { type: data.content_type });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = data.filename;
          a.click();
          URL.revokeObjectURL(url);
          copyWithFeedback('', `hld-${fmt}`);
          setHldExportLoading(fmt, false);
          return;
        } catch { /* fall through */ }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
        clearSession();
        setHldExportLoading(fmt, false);
        return;
      }
      set({ error: `HLD export failed: ${err.message}` });
    }
    setHldExportLoading(fmt, false);
  };

  const handleExportDiagram = async (format) => {
    setExportLoading(format, true);
    try {
      const data = await api.post(`/diagrams/${state.diagramId}/export-diagram?format=${format}`);
      const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
      const blob = new Blob([content], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = data.filename || `archmorph-diagram.${format === 'excalidraw' ? 'excalidraw' : format === 'drawio' ? 'drawio' : 'vdx'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (err.status === 404) {
        const restored = await tryRestoreSession(state.diagramId);
        if (!restored) {
          set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
          clearSession();
          setExportLoading(format, false);
          return;
        }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload' });
        clearSession();
        setExportLoading(format, false);
        return;
      }
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
      });
      addChatMessage({
        role: 'assistant',
        content: data.reply || data.message || 'Done.',
        changes: data.changes_summary || [],
        services: data.services_added || [],
      });
      if (data.code && !data.error) {
        set({ iacCode: data.code });
      }
    } catch {
      addChatMessage({ role: 'assistant', content: 'Sorry, couldn\'t connect to the IaC assistant.' });
    }
    set({ iacChatLoading: false });
    setTimeout(() => iacChatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handleGenerateHld = async () => {
    set({ hldLoading: true, error: null });
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 180_000);
      activeTimeoutsRef.current.push(timeout);
      const data = await api.post(`/diagrams/${state.diagramId}/generate-hld`, undefined, controller.signal);
      clearTimeout(timeout);
      activeTimeoutsRef.current = activeTimeoutsRef.current.filter(id => id !== timeout);
      if (data.hld) set({ hldData: data });
    } catch (err) {
      if (err.status === 404) {
        const restored = await tryRestoreSession(state.diagramId);
        if (restored) {
          try {
            const controller2 = new AbortController();
            const timeout2 = setTimeout(() => controller2.abort(), 180_000);
            activeTimeoutsRef.current.push(timeout2);
            const data = await api.post(`/diagrams/${state.diagramId}/generate-hld`, undefined, controller2.signal);
            clearTimeout(timeout2);
            if (data.hld) set({ hldData: data, hldLoading: false });
            return;
          } catch { /* fall through */ }
        }
        set({ error: 'Your session has expired. Please re-upload your diagram to continue.', step: 'upload', hldLoading: false });
        clearSession();
        return;
      }
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

  // ── Render ──
  const steps = STEPS.map(s => ({
    ...s,
    canNav: s.id === 'upload' ? true
      : s.id === 'questions' || s.id === 'results' ? !!state.analysis
      : s.id === 'iac' ? !!state.iacCode
      : false,
  }));

  return (
    <div className="space-y-6">
      {/* Progress Steps */}
      <div className="flex items-center justify-center gap-2 text-xs font-medium">
        {steps.map((s, i, arr) => {
          const isActive = state.step === s.id;
          const isPast = arr.findIndex(x => x.id === state.step) > i;
          const clickable = s.canNav && !isActive && state.step !== 'analyzing';
          return (
            <React.Fragment key={s.id}>
              {clickable ? (
                <button
                  type="button"
                  onClick={() => set({ step: s.id })}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-all duration-150 cursor-pointer border-none bg-transparent select-none ${
                    isPast ? 'text-cta hover:bg-cta/15 hover:scale-105' : 'text-text-muted hover:bg-cta/10 hover:text-cta'
                  }`}
                  title={`Go to ${s.label}`}
                >
                  {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                  <span className={`underline decoration-dotted underline-offset-2 ${isActive ? '' : 'hidden sm:inline'}`}>{s.label}</span>
                </button>
              ) : (
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-colors ${
                    isActive ? 'bg-cta/15 text-cta' :
                    isPast ? 'text-cta' : 'text-text-muted'
                  }`}
                >
                  {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                  <span className={isActive ? '' : 'hidden sm:inline'}>{s.label}</span>
                </div>
              )}
              {i < arr.length - 1 && <ChevronRight className="w-4 h-4 text-text-muted" />}
            </React.Fragment>
          );
        })}
      </div>

      {/* Error */}
      {state.error && (
        <Card className="p-4 border-danger/30" role="alert" aria-live="assertive">
          <div className="flex items-center gap-3">
            <XCircle className="w-5 h-5 text-danger shrink-0" aria-hidden="true" />
            <p className="text-sm text-danger">{state.error}</p>
            <button onClick={() => set({ error: null })} className="ml-auto cursor-pointer hover:bg-secondary rounded-lg p-1 transition-colors" aria-label="Dismiss error" title="Dismiss"><X className="w-4 h-4 text-text-muted" /></button>
          </div>
        </Card>
      )}

      {/* Step: Upload */}
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

      {/* Step: Analyzing */}
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
            </div>
          </div>
        </Card>
      )}

      {/* Step: Questions */}
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

      {/* Step: Results */}
      {state.step === 'results' && state.analysis && (
        <AnalysisResults
          analysis={state.analysis}
          loading={state.loading}
          iacFormat={state.iacFormat}
          exportLoading={state.exportLoading}
          hldLoading={state.hldLoading}
          hldData={state.hldData}
          hldTab={state.hldTab}
          hldExportLoading={state.hldExportLoading}
          hldIncludeDiagrams={state.hldIncludeDiagrams}
          copyFeedback={state.copyFeedback}
          onSetStep={(step) => set({ step })}
          onGenerateIac={handleGenerateIac}
          onGenerateHld={handleGenerateHld}
          onExportDiagram={handleExportDiagram}
          onSetHldTab={(tab) => set({ hldTab: tab })}
          onSetHldIncludeDiagrams={(v) => set({ hldIncludeDiagrams: v })}
          onHldExport={handleHldExport}
          onCopyWithFeedback={copyWithFeedback}
        />
      )}

      {/* Step: IaC Code */}
      {state.step === 'iac' && state.iacCode && (
        <div className="space-y-6">
          {/* CostPanel hidden during beta — no money-related UI */}
          <IaCViewer
            iacCode={state.iacCode}
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
          <div className="flex items-center justify-between">
            <Button onClick={() => set({ step: 'results' })} variant="ghost" icon={Eye}>Back to Results</Button>
            {state.confirmReset ? (
              <div className="flex items-center gap-2 bg-secondary rounded-lg px-3 py-2 border border-border animate-fade-in">
                <span className="text-xs text-text-secondary">Discard current translation?</span>
                <Button onClick={reset} variant="danger" size="sm">Yes, Start Over</Button>
                <Button onClick={() => set({ confirmReset: false })} variant="ghost" size="sm">Cancel</Button>
              </div>
            ) : (
              <Button onClick={() => set({ confirmReset: true })} variant="secondary" icon={Upload}>New Translation</Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

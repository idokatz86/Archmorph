import React, { useState, useEffect, useRef } from 'react';
import api from '../../services/apiClient';

const API_BASE_URL = '/api/v1/deployments'; // For standard execution
const PREFLIGHT_URL = '/api/deploy/preflight-check';

const DeployPanel = ({ templateSource = 'main.bicep', parameters = {}, provider = 'azure', canvasState = null }) => {
  const [step, setStep] = useState(1); // 1: Init, 2: Preview, 3: Deploying/Terminal
  const [loading, setLoading] = useState(false);
  const [preflightData, setPreflightData] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  const logsEndRef = useRef(null);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  useEffect(() => {
    if (step === 1 && !preflightData && !loading && canvasState) {
      runPreflight();
    }
  // eslint-disable-next-line
  }, [step, canvasState]);

  useEffect(() => {
    let eventSource = null;

    if (step === 3 && jobId && (status === 'running' || status === 'executing')) {
      eventSource = new EventSource(`${API_BASE_URL}/${jobId}/stream`);

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setLogs((prev) => [...prev, data.message || event.data]);
        } catch (e) {
          setLogs((prev) => [...prev, event.data]);
        }
      };

      eventSource.onerror = (err) => {
        console.error('SSE Error:', err);
        eventSource.close();
        setStatus('completed-or-failed');
      };
    }

    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [step, jobId, status]);

  const runPreflight = async () => {
    try {
      setLoading(true);
      const res = await fetch(PREFLIGHT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: "default",
          canvas_state: canvasState
        })
      });
      if (!res.ok) throw new Error(`Preflight failed: ${res.status}`);
      const data = await res.json();
      setPreflightData(data);
    } catch (err) {
      console.error("Preflight Error:", err);
    } finally {
      setLoading(false);
    }
  };

  const handlePreview = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const payload = {
        provider,
        template_source: templateSource,
        parameters
      };

      const res = await fetch(`${API_BASE_URL}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`Preview failed with status ${res.status}`);

      const data = await res.json();
      setPreviewData(data.preview_data || data);
      setStep(2);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDeploy = async () => {
    try {
      setLoading(true);
      setError(null);

      const payload = {
        provider,
        template_source: templateSource,
        parameters
      };

      const res = await fetch(`${API_BASE_URL}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error(`Execute failed with status ${res.status}`);

      const data = await res.json();
      setJobId(data.job_id);
      setStatus('running');
      setStep(3);
      setLogs(['--- Deployment Started ---']);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async () => {
    if (!jobId) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE_URL}/${jobId}/rollback`, { method: 'POST' });
      if (!res.ok) throw new Error('Rollback failed');
      
      setLogs((prev) => [...prev, '--- Rollback Initiated ---']);
      setStatus('rolling-back');
    } catch (err) {
      setError('Could not rollback: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setStep(1);
    setPreviewData(null);
    setJobId(null);
    setLogs([]);
    setStatus(null);
    setError(null);
  };

  return (
    <div className="w-full max-w-4xl mx-auto p-6 bg-surface rounded-lg shadow-md border border-border font-sans">
      
      <div className="mb-6 border-b border-border pb-4 flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-text-primary">Deployment Panel</h2>
          <p className="text-sm text-text-muted">One-Click Infrastructure Provisioning</p>
        </div>
        
        <div className="flex space-x-2 text-sm font-medium">
          <span className={`px-3 py-1 rounded-full ${step === 1 ? 'bg-cta/15 text-cta' : 'text-text-muted'}`}>1. Init</span>
          <span className={`px-3 py-1 rounded-full ${step === 2 ? 'bg-cta/15 text-cta' : 'text-text-muted'}`}>2. Preview</span>
          <span className={`px-3 py-1 rounded-full ${step === 3 ? 'bg-cta/15 text-cta' : 'text-text-muted'}`}>3. Deploy</span>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-4 text-sm text-red-700 bg-red-100 rounded-lg" role="alert">
          {error}
        </div>
      )}

      {/* STEP 1: INITIAL STATE */}
      {step === 1 && (
        <div className="flex flex-col items-center justify-center py-6 space-y-6">
          <p className="text-gray-600 dark:text-gray-300 text-center">
            Ready to deploy your infrastructure to <strong>{provider.toUpperCase()}</strong>.
          </p>

          {/* PREFLIGHT CHECK DATA */}
          {preflightData && (
            <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
              <div className="bg-yellow-50 dark:bg-yellow-900 border border-yellow-200 dark:border-yellow-700 rounded p-4">
                <h3 className="font-semibold text-yellow-800 dark:text-yellow-200 mb-2">Security Compliance</h3>
                <p className="text-sm">Score: {preflightData.security?.score}/100 ({preflightData.security?.status})</p>
                {preflightData.security?.findings?.length > 0 ? (
                  <ul className="list-disc list-inside text-xs mt-2 text-yellow-700 dark:text-yellow-300 ml-2 space-y-1">
                    {preflightData.security.findings.map((f, i) => (
                      <li key={i}><strong>{f.resource}:</strong> {f.issue}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs mt-2 text-green-600">All checks passed!</p>
                )}
              </div>
              <div className="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-700 rounded p-4">
                <h3 className="font-semibold text-blue-800 dark:text-blue-200 mb-2">FinOps Estimate</h3>
                <p className="text-xl font-bold text-blue-900 dark:text-blue-100 tracking-tight">
                  ${preflightData.finops?.total_monthly_estimate?.toFixed(2)} <span className="text-sm font-normal">/ mo</span>
                </p>
                <div className="mt-2 text-xs text-blue-700 dark:text-blue-300 max-h-24 overflow-y-auto">
                  {preflightData.finops?.breakdown?.map((item, i) => (
                    <div key={i} className="flex justify-between mt-1 border-b border-blue-200 dark:border-blue-700 pb-1">
                      <span>{item.resource} ({item.assumed_sku})</span>
                      <span className="font-semibold">${item.monthly_cost_usd?.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded p-4 text-left max-h-64 overflow-y-auto">
            <p className="text-xs text-gray-500 mb-2 font-semibold uppercase tracking-wider">TARGET TEMPLATE ({provider.toUpperCase()})</p>
            <pre className="text-xs font-mono text-gray-800 dark:text-gray-300 whitespace-pre-wrap">
              {templateSource}
            </pre>
          </div>

          <div className="flex space-x-3 mt-4">
             <button 
                onClick={runPreflight} 
                disabled={loading || !canvasState}
                className="px-4 py-2 border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium rounded transition-colors text-sm disabled:opacity-50"
              >
                {loading ? 'Analyzing...' : 'Refresh Preflight'}
              </button>
            <button 
              onClick={handlePreview} 
              disabled={loading || preflightData?.security?.status === 'Fail'}
              title={preflightData?.security?.status === 'Fail' ? "Cannot deploy with critical security risks" : ""}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded shadow transition-colors disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Run Preview'}
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: PREVIEW STATE */}
      {step === 2 && (
        <div className="space-y-4">
          <div className="p-4 bg-gray-50 dark:bg-gray-900 rounded border border-gray-200 dark:border-gray-700 max-h-64 overflow-y-auto">
            <h3 className="text-lg font-semibold mb-2 text-gray-700 dark:text-gray-200">Execution Plan Preview</h3>
            <pre className="text-xs text-gray-800 dark:text-gray-300 whitespace-pre-wrap font-mono">
              {typeof previewData === 'object' ? JSON.stringify(previewData, null, 2) : previewData || 'No preview data returned.'}
            </pre>
          </div>
          
          <div className="flex justify-end space-x-3 mt-4">
            <button 
              onClick={reset}
              className="px-4 py-2 border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium rounded transition-colors"
            >
               Cancel
            </button>
            <button 
              onClick={handleDeploy} 
              disabled={loading}
              className="px-6 py-2 bg-green-600 hover:bg-green-700 text-white font-medium rounded shadow transition-colors disabled:opacity-50"
            >
              {loading ? 'Starting Deploy...' : 'Confirm & Deploy'}
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: DEPLOYMENT/TERMINAL STATE */}
      {step === 3 && (
        <div className="space-y-4 flex flex-col h-full">
          <div className="flex justify-between items-center bg-gray-900 px-4 py-2 rounded-t-lg border-b border-gray-700">
            <div className="flex items-center space-x-2">
              <span className="w-3 h-3 rounded-full bg-red-500"></span>
              <span className="w-3 h-3 rounded-full bg-yellow-500"></span>
              <span className="w-3 h-3 rounded-full bg-green-500"></span>
              <span className="text-gray-400 text-xs ml-4 font-mono">job: {jobId}</span>
            </div>
            {status && <span className="text-blue-400 text-xs font-mono animate-pulse">{status.toUpperCase()}</span>}
          </div>
          
          <div className="bg-black p-4 h-80 overflow-y-auto font-mono text-sm shadow-inner rounded-b-lg scrollbar-thin scrollbar-thumb-gray-600 border border-gray-800">
            {logs.length === 0 && <span className="text-gray-500">Connecting to stream...</span>}
            {logs.map((log, index) => (
              <div key={index} className="text-green-400 mb-1">
                <span className="text-gray-600 mr-2">❯</span> {log}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>

          <div className="flex justify-between mt-4">
             <button 
                onClick={reset}
                className="px-4 py-2 border border-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 font-medium rounded transition-colors text-sm"
              >
                Start Over
              </button>

             <button 
              onClick={handleRollback} 
              disabled={loading || status === 'rolling-back'}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white font-medium rounded shadow transition-colors block ml-auto text-sm disabled:opacity-50"
            >
              {loading && status === 'rolling-back' ? 'Rolling back...' : 'Abort & Rollback'}
            </button>
          </div>
        </div>
      )}

    </div>
  );
};

export default DeployPanel;

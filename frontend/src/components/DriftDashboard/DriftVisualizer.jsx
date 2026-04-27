import React, { useState } from 'react';
import { AlertTriangle, FlaskConical, RefreshCw, ShieldCheck } from 'lucide-react';
import { Card } from '../ui';
import EmptyState from '../EmptyState';
import api from '../../services/apiClient';
import { CloudCredentialsModal } from './CloudCredentialsModal';

const DriftBadge = ({ status }) => {
  const colors = {
    green: "bg-green-100 text-green-800",
    yellow: "bg-yellow-100 text-yellow-800",
    red: "bg-red-100 text-red-800",
    grey: "bg-gray-100 text-gray-800"
  };
  return (
    <span className={`px-2 py-1 text-xs font-semibold rounded-full ${colors[status] || ""}`}>
      {status.toUpperCase()}
    </span>
  );
};

export const DriftVisualizer = ({ driftResults: initialDrift, onSync }) => {
  return <DriftVisualizerContent driftResults={initialDrift} onSync={onSync} />;
};

const SAMPLE_DRIFT_PAYLOAD = {
  designed_state: {
    nodes: [
      { id: 'web-app-prod', name: 'Frontend App', type: 'static_web_app', region: 'westeurope', sku: 'standard' },
      { id: 'api-prod', name: 'API Container', type: 'container_app', region: 'westeurope', sku: 'consumption' },
      { id: 'postgres-prod', name: 'PostgreSQL', type: 'postgres', region: 'westeurope', sku: 'b1ms' },
    ],
  },
  live_state: {
    nodes: [
      { resource_id: 'web-app-prod', name: 'Frontend App', resource_type: 'static_web_app', region: 'westeurope', sku: 'standard' },
      { resource_id: 'api-prod', name: 'API Container', resource_type: 'container_app', region: 'westeurope', sku: 'dedicated' },
      { resource_id: 'redis-prod', name: 'Redis Cache', resource_type: 'redis', region: 'westeurope', sku: 'basic' },
    ],
  },
};

const DriftVisualizerContent = ({ driftResults: initialDrift, onSync }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [driftResults, setDriftResults] = useState(initialDrift || null);
  const [finopsResults, setFinopsResults] = useState(null);
  const [complianceResults, setComplianceResults] = useState(null);
  const [selectedProvider, setSelectedProvider] = useState('azure');
  const [activeTab, setActiveTab] = useState('drift');
  const [showCredentialsModal, setShowCredentialsModal] = useState(false);

  const simulateConnection = () => {
    setShowCredentialsModal(true);
  };

  const runSampleAudit = async () => {
    setLoading(true);
    setError(null);
    try {
      const sampleDrift = await api.post('/drift/detect', SAMPLE_DRIFT_PAYLOAD);
      setDriftResults(sampleDrift);
      setFinopsResults(null);
      setActiveTab('drift');
    } catch (err) {
      setError(err?.message || 'Failed to run sample drift audit.');
    } finally {
      setLoading(false);
    }
  };

  const handleCredentialsSuccess = async (sessionToken) => {
    setShowCredentialsModal(false);
    await performScan(sessionToken);
  };

  const performScan = async (sessionToken) => {
    setLoading(true);
    setError(null);
    try {
      // Create a real cloud architecture scan using stored cloud credentials
      const scanResponse = await api.auth('POST', `/scanner/run/${selectedProvider}`, { token: sessionToken });
      
      // Perform genuine drift detection between design & observed reality
      const driftPayload = {
        designed_state: { nodes: [] }, // Will integrate real diagram state later
        live_state: { nodes: scanResponse?.data?.resources || [] }
      };
      
      const realDrift = await api.post('/drift/detect', driftPayload);
      setDriftResults(realDrift);
      
      if (scanResponse?.data?.finops) {
        setFinopsResults(scanResponse.data.finops);
      }
    } catch (err) {
      setError(err?.message || "Failed to scan live infrastructure. Make sure you connected your cloud account.");
    } finally {
      setLoading(false);
    }
  };

  if (!driftResults) {
    return (
      <>
      <div className="w-full max-w-4xl mx-auto mb-4 mt-8">
        <div className="p-4 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5" />
          <div>
            <h4 className="font-semibold text-sm">Alpha Stage Feature</h4>
            <p className="text-sm mt-1">
              Drift Detection is currently in alpha. We are actively developing this capability, which means you may experience occasional instability or inaccurate detection results. The core functionality is enabled for early testing and feedback.
            </p>
          </div>
        </div>
      </div>
      <EmptyState
        icon={ShieldCheck}
        title="No Active Audits"
        description="Connect your live cloud environment or run an IaC scan to detect architectural drift between your design document and reality."
      >
        <div className="flex flex-col items-center">
          <div className="w-full max-w-xs text-left mb-6">
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Cloud Provider
            </label>
            <select
              value={selectedProvider}
              onChange={(e) => setSelectedProvider(e.target.value)}
              disabled={loading}
              className="w-full px-3 py-2 bg-white border border-slate-300 rounded-md text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="azure">Azure</option>
              <option value="aws">AWS</option>
              <option value="gcp">Google Cloud</option>
            </select>
          </div>

          {/* New Connection Guide on Empty State */}
          <div className="w-full text-left bg-slate-50 p-6 rounded-lg border border-slate-200">
            <h4 className="font-semibold text-slate-800 mb-4 text-sm uppercase tracking-wider border-b pb-2">Step-by-step Connection Guide</h4>
            
            {selectedProvider === 'aws' && (
              <ol className="list-decimal pl-5 space-y-3 text-sm text-slate-600">
                <li><strong className="text-slate-800">Create an IAM Role:</strong> Log into AWS Console and navigate to IAM &gt; Roles.</li>
                <li><strong className="text-slate-800">Set Trust Relationship:</strong> Select "Another AWS account" (ID: <code className="bg-slate-200 px-1 py-0.5 rounded">123456789012</code>) and require external ID (<code className="bg-slate-200 px-1 py-0.5 rounded">ext-xxxx-xxxx</code>).</li>
                <li><strong className="text-slate-800">Attach Policies:</strong> Attach the <strong>ReadOnlyAccess</strong> managed policy.</li>
                <li>Save the role and click <strong>Connect Cloud Account</strong> below to input your Role ARN.</li>
              </ol>
            )}

            {selectedProvider === 'azure' && (
              <ol className="list-decimal pl-5 space-y-3 text-sm text-slate-600">
                <li><strong className="text-slate-800">Register an Application:</strong> In the Azure Portal, go to Microsoft Entra ID &gt; App registrations and create a new app named <code className="bg-slate-200 px-1 py-0.5 rounded">Archmorph Drift</code>.</li>
                <li><strong className="text-slate-800">Generate Secret:</strong> Under Certificates &amp; secrets, generate a new client secret. Copy the value immediately.</li>
                <li><strong className="text-slate-800">Assign Role:</strong> Go to Subscriptions &gt; Access control (IAM) and assign the <strong>Reader</strong> role to your new app.</li>
                <li>Click <strong>Connect Cloud Account</strong> below to input your credentials.</li>
              </ol>
            )}

            {selectedProvider === 'gcp' && (
              <ol className="list-decimal pl-5 space-y-3 text-sm text-slate-600">
                <li><strong className="text-slate-800">Create Service Account:</strong> In the GCP Console, go to IAM &amp; Admin &gt; Service Accounts and create a new account named <code className="bg-slate-200 px-1 py-0.5 rounded">archmorph-drift</code>.</li>
                <li><strong className="text-slate-800">Grant Access:</strong> Give the service account the <strong>Viewer</strong> role for read-only access.</li>
                <li><strong className="text-slate-800">Download Key:</strong> Generate a new JSON key for the service account and download it.</li>
                <li>Click <strong>Connect Cloud Account</strong> below to upload your JSON file.</li>
              </ol>
            )}
          </div>

          {error && (
            <div className="mt-4 p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200 w-full">
              {error}
            </div>
          )}
          <button 
            onClick={simulateConnection}
            disabled={loading}
            className="mt-6 px-4 py-2 bg-blue-600 text-white font-medium rounded shadow hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-2"
          >
            {loading && (
              <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            )}
            {loading ? 'Evaluating infrastructure...' : 'Connect Cloud Account'}
          </button>
          <button
            onClick={runSampleAudit}
            disabled={loading}
            className="mt-3 px-4 py-2 bg-slate-900 text-white font-medium rounded shadow hover:bg-slate-800 disabled:opacity-50 inline-flex items-center gap-2"
          >
            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <FlaskConical className="w-4 h-4" />}
            Run Sample Drift Audit
          </button>
        </div>
      </EmptyState>
      {showCredentialsModal && (
        <CloudCredentialsModal 
          provider={selectedProvider} 
          onClose={() => setShowCredentialsModal(false)}
          onSuccess={handleCredentialsSuccess}
        />
      )}
    </>
  );
}

  return (
    <Card className="w-full max-w-4xl mx-auto shadow-sm">
      <div className="flex flex-col space-y-1.5 p-6 border-b">
        <div className="mb-4 p-4 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5" />
          <div>
            <h4 className="font-semibold text-sm">Alpha Stage Feature</h4>
            <p className="text-sm mt-1">
              Drift Detection is currently in alpha. We are actively developing this capability, which means you may experience occasional instability or inaccurate detection results. The core functionality is enabled for early testing and feedback.
            </p>
          </div>
        </div>
        <h3 className="text-2xl font-semibold leading-none tracking-tight">Architecture Drift Detection</h3>
        {driftResults.summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-4">
            {[
              ['Matched', driftResults.summary.matched],
              ['Modified', driftResults.summary.modified],
              ['Shadow', driftResults.summary.shadow],
              ['Missing', driftResults.summary.missing],
            ].map(([label, value]) => (
              <div key={label} className="bg-slate-50 border border-slate-100 rounded-md p-3">
                <p className="text-xs text-slate-500">{label}</p>
                <p className="text-xl font-bold text-slate-900">{value}</p>
              </div>
            ))}
          </div>
        )}
        
        <div className="flex pt-4 mt-2">
          <button 
            className={`px-4 py-2 font-medium ${activeTab === 'drift' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-slate-500 hover:text-slate-700'}`}
            onClick={() => setActiveTab('drift')}
          >
            Drift Detection
          </button>
          
          {finopsResults && (
            <button 
              className={`px-4 py-2 font-medium flex items-center justify-center ${activeTab === 'finops' ? 'border-b-2 border-green-600 text-green-600' : 'text-slate-500 hover:text-slate-700'}`}
              onClick={() => setActiveTab('finops')}
            >
              FinOps Optimizations
              <span className="ml-2 bg-green-100 text-green-800 py-0.5 px-2 rounded-full text-xs font-bold">{finopsResults.total_optimizations}</span>
            </button>
          )}
        </div>
      </div>
      
      <div className="p-6">
        {activeTab === 'drift' ? (
          <>
            <div className="flex justify-between items-center mb-6 p-4 bg-slate-50 rounded-md">
          <div>
            <span className="text-sm font-medium text-slate-500">Overall Health Score</span>
            <div className="text-2xl font-bold">{(driftResults.overall_score * 100).toFixed(0)}%</div>
          </div>
          <button 
            onClick={onSync}
            className="px-4 py-2 bg-blue-600 text-white font-medium rounded shadow hover:bg-blue-700"
          >
            Sync Real to Diagram
          </button>
        </div>

        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Detailed Findings</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm text-left">
              <thead className="bg-slate-100 text-slate-600">
                <tr>
                  <th className="px-4 py-2">Resource ID</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Message</th>
                  <th className="px-4 py-2">Recommendation</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {driftResults.detailed_findings?.map((finding, idx) => (
                  <tr key={idx} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium">{finding.id}</td>
                    <td className="px-4 py-3">
                      <DriftBadge status={finding.status} />
                    </td>
                    <td className="px-4 py-3 text-slate-600">{finding.message}</td>
                    <td className="px-4 py-3 text-slate-600">{finding.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </>
        ) : (
          <div className="space-y-6 animate-in fade-in duration-300">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-green-50 border border-green-100 rounded-md">
                <h4 className="text-green-800 font-medium text-sm">Total Optimizations</h4>
                <p className="text-3xl font-bold text-green-600 mt-1">{finopsResults.total_optimizations}</p>
              </div>
              <div className="p-4 bg-blue-50 border border-blue-100 rounded-md">
                <h4 className="text-blue-800 font-medium text-sm">Quick Wins</h4>
                <p className="text-3xl font-bold text-blue-600 mt-1">{finopsResults.quick_wins}</p>
              </div>
              <div className="p-4 bg-slate-50 border border-slate-200 rounded-md">
                <h4 className="text-slate-700 font-medium text-sm">Scanned Resources</h4>
                <p className="text-3xl font-bold text-slate-600 mt-1">{finopsResults.scanned_resources}</p>
              </div>
            </div>
            
            <div className="space-y-4 mt-6">
              <h3 className="text-lg font-semibold border-b pb-2">Saving Recommendations</h3>
              {finopsResults.optimizations?.map((opt, idx) => (
                <div key={idx} className="border border-slate-200 bg-white rounded-md p-5 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex justify-between items-start">
                    <h4 className="font-semibold text-slate-800 flex items-center gap-2">
                       <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                         <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                       </svg>
                       {opt.title}
                    </h4>
                    <span className="bg-green-100 text-green-800 text-xs px-2.5 py-1 rounded-full font-medium">{opt.estimated_savings}</span>
                  </div>
                  <p className="text-sm text-slate-600 mt-3 pl-7">{opt.description}</p>
                  
                  <div className="mt-4 pl-7">
                    <h5 className="text-xs font-semibold text-slate-500 uppercase">Affected Resources ({opt.services_affected?.length || 0})</h5>
                    <div className="flex flex-wrap gap-2 mt-1.5">
                      {opt.services_affected?.map((svc, sIdx) => (
                        <span key={sIdx} className="bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-xs font-mono border border-slate-200">
                          {svc}
                        </span>
                      ))}
                    </div>
                  </div>
                  
                  <div className="mt-4 pl-7 pt-3 border-t border-slate-100">
                     <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Action:</span> {opt.action_steps?.join(' → ') || 'Follow provider documentation'}</p>
                  </div>
                </div>
              ))}
              {finopsResults.optimizations?.length === 0 && (
                <div className="text-center py-10 bg-slate-50 rounded-lg border border-dashed">
                   <p className="text-slate-500 font-medium">Looking good! No immediate cost-saving optimizations found.</p>
                </div>
              )}
            </div>
          </div>
)}

        {activeTab === 'compliance' && complianceResults && (
          <div className="space-y-4 pt-4">
            <h3 className="text-xl font-bold">Compliance Posture</h3>
            <p className="text-gray-600">Overall Score: {complianceResults.overall_score}/100</p>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(complianceResults.frameworks || {}).map(([fw, data]) => (
                <div key={fw} className="p-4 border rounded shadow-sm bg-white">
                  <div className="flex justify-between">
                    <span className="font-bold">{fw}</span>
                    <span className={`px-2 py-1 text-sm rounded ${data.score >= 80 ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                      {data.status} ({data.score}%)
                    </span>
                  </div>
                  <p className="text-sm mt-2 text-gray-500">
                    {data.passed_rules || (data.total_violations === undefined ? "0" : data.total_rules - data.total_violations)} / {data.total_rules} Controls Passed
                  </p>
                </div>
              ))}
            </div>

            {complianceResults.violations && complianceResults.violations.length > 0 && (
              <div className="mt-8">
                <h4 className="text-lg font-bold">Policy Violations</h4>
                <div className="space-y-4 mt-4">
                  {complianceResults.violations.map((v, i) => (
                    <div key={i} className="p-4 border border-l-4 border-l-red-500 rounded bg-white">
                      <h5 className="font-bold text-red-700">{v.title}</h5>
                      <p className="text-sm text-gray-600 mt-1">{v.description}</p>
                      <div className="mt-2 text-sm">
                        <strong>Affected Resource:</strong> {v.resource_name} ({v.resource_id})
                      </div>
                      <div className="mt-2 text-sm">
                        <strong>Remediation:</strong> {v.remediation}
                      </div>
                      <div className="mt-2 flex space-x-2">
                        {v.frameworks.map(f => (
                          <span key={f} className="bg-gray-100 text-xs px-2 py-1 rounded">{f}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </Card>
  );
};

export default DriftVisualizer;
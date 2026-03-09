import React, { useState } from 'react';
import { Card } from '../ui';
import api from '../../services/apiClient';

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [driftResults, setDriftResults] = useState(initialDrift || null);

  const simulateConnection = async () => {
    setLoading(true);
    setError(null);
    try {
      // Create a real cloud architecture scan using stored azure credentials
      const scanResponse = await api.post('/scanner/run/azure');
      
      // Perform genuine drift detection between design & observed reality
      const driftPayload = {
        designed_state: { nodes: [] }, // Will integrate real diagram state later
        live_state: { nodes: scanResponse?.data?.resources || [] }
      };
      
      const realDrift = await api.post('/drift/detect', driftPayload);
      setDriftResults(realDrift);
    } catch (err) {
      setError(err?.message || "Failed to scan live infrastructure. Make sure you connected your cloud account.");
    } finally {
      setLoading(false);
    }
  };

  if (!driftResults) {
    return (
      <Card className="w-full max-w-4xl mx-auto shadow-sm mt-8 border-dashed border-2">
        <div className="flex flex-col items-center justify-center p-12 text-center text-slate-500">
          <svg className="w-12 h-12 mb-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
          <h3 className="text-lg font-semibold text-slate-700">No Active Audits</h3>
          <p className="mt-2 text-sm max-w-md">
            Connect your live Azure environment or run an IaC scan to detect architectural drift between your design document and reality.
          </p>
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
        </div>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-4xl mx-auto shadow-sm">
      <div className="flex flex-col space-y-1.5 p-6">
        <h3 className="text-2xl font-semibold leading-none tracking-tight">Architecture Drift Detection</h3>
      </div>
      <div className="p-6 pt-0">
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Card>
  );
};

export default DriftVisualizer;
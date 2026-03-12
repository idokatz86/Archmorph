import React, { useState } from 'react';
import { Play, AlertTriangle, Check, Terminal } from 'lucide-react';
import apiClient from '../../services/apiClient';

export default function DeployPanel({ parsedResults, isLoading }) {
  const [ isDeploying, setIsDeploying ] = useState(false);
  const [ logs, setLogs ] = useState([]);
  const [ error, setError ] = useState(null);

  const handleDeploy = async () => {
    setIsDeploying(true);
    setLogs([]);
    setError(null);

    try {
      const p_id = parsedResults?.projectId || 'unknown';
      const response = await fetch(`${apiClient.baseUrl}/api/deploy/execute/${p_id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${sessionStorage.getItem('token')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          project_id: p_id,
          iac_code: parsedResults?.terraform_code || null,
          canvas_state: parsedResults?.canvas_state || null
        })
      });

      if (!response.ok) throw new Error('Deployment initiation failed');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        setLogs((prev) => [...prev, ...text.split('\n').filter(Boolean)]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsDeploying(false);
    }
  };

  if (isLoading) return null;

  return (
    <div className="bg-white p-8 rounded-xl shadow-sm border border-slate-200 mt-8 mt-4 text-center">
      <div className="flex flex-col items-center justify-center space-y-4 py-12 text-slate-500">
        <Terminal className="w-12 h-12 text-slate-300" />
        <h2 className="text-2xl font-bold text-slate-700">Deployments Coming Soon</h2>
        <p className="max-w-md mx-auto text-slate-500">
          In an upcoming release, you will be able to perform 1-click deployments directly 
          into your cloud environment right from this panel using the generated IaC code.
        </p>
      </div>
    </div>
  );
}

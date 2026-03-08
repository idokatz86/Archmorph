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
    <div className="bg-white p-8 rounded-xl shadow-sm border border-slate-200 mt-8">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <Terminal className="w-6 h-6 text-indigo-600" />
          <h2 className="text-xl font-bold text-slate-900">One Click Deploy</h2>
        </div>
        <button 
          onClick={handleDeploy} 
          disabled={isDeploying || !parsedResults}
          className={`flex items-center px-4 py-2 rounded-lg text-white font-medium transition-colors ${
            isDeploying ? 'bg-gray-400 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700'
          }`}
        >
          <Play className="w-4 h-4 mr-2" />
          { isDeploying ? 'Deploying...' : 'Deploy to Azure' }
        </button>
      </div>

      { error && 
        <div className="p-4 bg-red-50 text-red-700 rounded-md mb-4 flex items-center">
          <AlertTriangle className="w-5 h-5 mr-2" /> {error}
        </div>
      }

      <div className="bg-gray-900 rounded-lg p-4 h-64 overflow-y-auto font-mono text-sm text-green-400 whitespace-pre-wrap">
        { logs.length === 0 && !isDeploying && (
          <div className="text-gray-500 italic">Deployment logs will appear here...</div>
        )}
        { logs.map((log, i) => (
          <div key={i} className={log.includes('ERROR') ? 'text-red-400' : log.includes('Complete') ? 'text-blue-400' : 'inherit'}>
            { log }
          </div>
        ))}
      </div>
    </div>
  );
}

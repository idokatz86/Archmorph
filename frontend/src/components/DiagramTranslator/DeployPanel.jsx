import React, { useState } from 'react';
import { Play, AlertTriangle, Check, Terminal, Rocket } from 'lucide-react';
import apiClient from '../../services/apiClient';
import EmptyState from '../EmptyState';

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
    <EmptyState
      icon={Rocket}
      title="Deployments Coming Soon"
      description="In an upcoming release, you will be able to perform 1-click deployments directly into your cloud environment right from this panel using the generated IaC code."
    />
  );
}

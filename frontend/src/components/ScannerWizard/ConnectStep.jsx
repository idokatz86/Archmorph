import React, { useState } from 'react';
import apiClient from '../../services/apiClient';

export default function ConnectStep({ provider, setProvider, onNext }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleConnect = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // Mock validation to fulfill #413/#414
      const res = await apiClient.post('/api/credentials/validate', { provider: provider || 'aws' });
      if (res.status === 'valid') {
        onNext();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-slate-800 p-6 rounded-lg border border-slate-700">
      <h3 className="text-xl text-white mb-4">Step 1: Connect to Cloud</h3>
      <div className="flex gap-4 mb-6">
        {['aws', 'azure', 'gcp'].map(p => (
          <button 
            key={p} 
            onClick={() => setProvider(p)}
            className={`px-4 py-2 rounded-lg border ${provider === p ? 'bg-blue-600 border-blue-500 text-white' : 'bg-slate-700 border-slate-600 text-slate-300'}`}
          >
            {p.toUpperCase()}
          </button>
        ))}
      </div>
      
      {error && <div className="p-3 bg-red-900/50 border border-red-500 rounded text-red-200 mb-4">{error}</div>}
      
      <button 
        onClick={handleConnect} 
        disabled={loading || !provider}
        className="px-6 py-2 bg-gradient-to-r from-blue-500 to-indigo-600 disabled:opacity-50 text-white rounded-md"
      >
        {loading ? 'Testing Connection...' : 'Connect & Continue'}
      </button>
    </div>
  );
}

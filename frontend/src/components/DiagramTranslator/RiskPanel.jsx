import React, { useState, useEffect } from 'react';
import { AlertTriangle, ShieldCheck, Info, Loader2 } from 'lucide-react';
import { Card, Button } from '../ui';
import api from '../../services/apiClient';

export default function RiskPanel({ diagramId }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchRisk() {
      if (!diagramId) return;
      try {
        setLoading(true);
        const res = await api.get(`/api/diagrams/${diagramId}/risk-score`);
        setData(res.data);
      } catch (err) {
        setError("Failed to load risk scorecard.");
      } finally {
        setLoading(false);
      }
    }
    fetchRisk();
  }, [diagramId]);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center text-gray-500">
        <Loader2 className="w-5 h-5 mr-3 animate-spin" />
        Consulting AI Migration Risk Engine...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-8 text-center text-red-500">
        <AlertTriangle className="mx-auto w-10 h-10 mb-2 opacity-50" />
        <p>{error}</p>
      </div>
    );
  }

  const { overall_score, risk_tier, factors, recommendations } = data;
  
  const tierColors = {
    low: "bg-green-100 text-green-800 border-green-200",
    moderate: "bg-yellow-100 text-yellow-800 border-yellow-200",
    high: "bg-orange-100 text-orange-800 border-orange-200",
    critical: "bg-red-100 text-red-800 border-red-200"
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold">Migration Risk Scorecard</h2>
          <p className="text-gray-500 text-sm">Quantitative analysis of architecture migration complexity.</p>
        </div>
        <div className={`px-4 py-2 rounded-lg border-2 ${tierColors[risk_tier] || "bg-gray-100"}`}>
          <div className="text-xs uppercase font-bold tracking-wider opacity-80">Overall Risk Score</div>
          <div className="text-3xl font-black">{overall_score.toFixed(0)}/100</div>
          <div className="text-sm font-semibold capitalize mt-1 mb-1">{risk_tier} Risk</div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {factors.map((f, i) => (
          <Card key={i} className="p-4 flex justify-between items-center bg-white shadow-sm border">
            <div>
              <div className="font-semibold text-gray-800">{f.name.replace(/_/g, ' ')}</div>
              <div className="text-xs text-gray-500 mt-1 capitalize">{f.impact} Impact Factor</div>
            </div>
            <div className="text-xl font-bold bg-blue-50 text-blue-800 px-3 py-1 rounded w-16 text-center">
              {f.score.toFixed(0)}
            </div>
          </Card>
        ))}
      </div>

      {recommendations?.length > 0 && (
        <Card className="p-6 border-blue-200 bg-blue-50">
          <h3 className="font-bold text-blue-900 mb-4 flex items-center">
            <ShieldCheck className="w-5 h-5 mr-2" /> Actionable Mitigations
          </h3>
          <ul className="space-y-3">
            {recommendations.map((rec, i) => (
              <li key={i} className="flex gap-2 text-sm text-blue-800">
                <span className="shrink-0 mt-0.5">•</span>
                <span>{rec}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

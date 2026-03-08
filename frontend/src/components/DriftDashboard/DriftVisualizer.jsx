import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/card';

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

export const DriftVisualizer = ({ driftResults, onSync }) => {
  if (!driftResults) return null;

  return (
    <Card className="w-full max-w-4xl mx-auto shadow-sm">
      <CardHeader>
        <CardTitle>Architecture Drift Detection</CardTitle>
      </CardHeader>
      <CardContent>
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
      </CardContent>
    </Card>
  );
};

export default DriftVisualizer;
import React from 'react';
import { CloudCog, Layers, Server, Rocket } from 'lucide-react';
import { Badge } from './ui';
import { APP_VERSION } from '../constants';

export default function Nav({ activeTab, setActiveTab, updateStatus }) {
  return (
    <header className="sticky top-0 z-50 bg-surface/80 backdrop-blur-xl border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-cta/15 flex items-center justify-center">
              <CloudCog className="w-5 h-5 text-cta" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-text-primary tracking-tight">Archmorph</h1>
              <p className="text-[10px] text-text-muted font-medium uppercase tracking-wider">Cloud Translator</p>
            </div>
          </div>
          <nav aria-label="Main navigation" className="flex items-center gap-1">
            {[
              { id: 'translator', label: 'Translator', icon: Layers },
              { id: 'services', label: 'Services', icon: Server },
              { id: 'roadmap', label: 'Roadmap', icon: Rocket },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                aria-current={activeTab === tab.id ? 'page' : undefined}
                className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors duration-200 cursor-pointer ${
                  activeTab === tab.id
                    ? 'bg-cta/10 text-cta'
                    : 'text-text-secondary hover:text-text-primary hover:bg-secondary'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {updateStatus && (
              <div className="flex items-center gap-2 text-xs text-text-muted">
                <div className={`w-2 h-2 rounded-full ${updateStatus.scheduler_running ? 'bg-cta animate-pulse' : 'bg-text-muted'}`} role="status" aria-label={updateStatus.scheduler_running ? 'Catalog live' : 'Catalog idle'} />
                <span>Catalog {updateStatus.scheduler_running ? 'Live' : 'Idle'}</span>
              </div>
            )}
            <Badge variant="azure">v{APP_VERSION}</Badge>
          </div>
        </div>
      </div>
    </header>
  );
}

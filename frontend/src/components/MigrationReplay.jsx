import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Play, Pause, SkipForward, RotateCcw, Zap, Database, Globe, Shield, Server, Cloud, ChevronRight } from 'lucide-react';

const SPEED_OPTIONS = [1, 2, 4];

const REPLAY_EVENTS = [
  { id: 1, time: 0, title: 'Scan Source Architecture', detail: 'Detected 12 AWS services across 3 regions', icon: Globe, color: 'text-sky-400' },
  { id: 2, time: 1, title: 'Analyze Dependencies', detail: 'Mapped 47 service connections and data flows', icon: Zap, color: 'text-amber-400' },
  { id: 3, time: 2, title: 'Identify Database Layer', detail: 'RDS PostgreSQL → Azure Database for PostgreSQL', icon: Database, color: 'text-emerald-400' },
  { id: 4, time: 3, title: 'Map Compute Services', detail: 'Lambda (8 functions) → Azure Functions', icon: Server, color: 'text-violet-400' },
  { id: 5, time: 4, title: 'Configure Networking', detail: 'VPC peering → Azure VNet with private endpoints', icon: Shield, color: 'text-rose-400' },
  { id: 6, time: 5, title: 'Provision Target Infra', detail: 'Terraform plan generated: 23 resources', icon: Cloud, color: 'text-cta' },
  { id: 7, time: 6, title: 'Validate & Deploy', detail: 'All health checks passed, zero-downtime cutover', icon: ChevronRight, color: 'text-emerald-400' },
];

export default function MigrationReplay() {
  const [currentStep, setCurrentStep] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const intervalRef = useRef(null);

  const totalSteps = REPLAY_EVENTS.length;
  const progress = totalSteps > 0 ? ((currentStep + 1) / totalSteps) * 100 : 0;

  const stop = useCallback(() => {
    clearInterval(intervalRef.current);
    intervalRef.current = null;
    setPlaying(false);
  }, []);

  const tick = useCallback(() => {
    setCurrentStep(prev => {
      if (prev >= totalSteps - 1) {
        stop();
        return prev;
      }
      return prev + 1;
    });
  }, [totalSteps, stop]);

  const startPlaying = useCallback(() => {
    if (currentStep >= totalSteps - 1) setCurrentStep(-1);
    setPlaying(true);
  }, [currentStep, totalSteps]);

  useEffect(() => {
    if (!playing) return;
    // Immediately advance one step then set interval
    tick();
    intervalRef.current = setInterval(tick, 1200 / speed);
    return () => clearInterval(intervalRef.current);
  }, [playing, speed, tick]);

  useEffect(() => () => clearInterval(intervalRef.current), []);

  const togglePlay = () => {
    if (playing) stop();
    else startPlaying();
  };

  const reset = () => {
    stop();
    setCurrentStep(-1);
  };

  const skipToEnd = () => {
    stop();
    setCurrentStep(totalSteps - 1);
  };

  const cycleSpeed = () => {
    const idx = SPEED_OPTIONS.indexOf(speed);
    setSpeed(SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length]);
  };

  const handleScrub = (e) => {
    stop();
    const val = parseInt(e.target.value, 10);
    setCurrentStep(val);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-cta/15 flex items-center justify-center">
          <Play className="w-5 h-5 text-cta" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-text-primary">Migration Replay</h2>
          <p className="text-xs text-text-muted">Step-by-step animated walkthrough</p>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-secondary rounded-xl p-4 border border-border space-y-4">
        {/* Progress bar */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-text-muted">
            <span>Step {Math.max(0, currentStep + 1)} of {totalSteps}</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="h-1.5 bg-surface rounded-full overflow-hidden">
            <div
              className="h-full bg-cta rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          {/* Scrubber */}
          <input
            type="range"
            min={-1}
            max={totalSteps - 1}
            value={currentStep}
            onChange={handleScrub}
            className="w-full accent-cta cursor-pointer"
            aria-label="Timeline scrubber"
          />
        </div>

        {/* Buttons */}
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={reset}
            className="p-2 rounded-lg bg-surface hover:bg-surface/80 text-text-muted hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Reset"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={togglePlay}
            className="p-3 rounded-xl bg-cta text-surface hover:bg-cta/90 transition-colors cursor-pointer shadow-lg shadow-cta/20"
            aria-label={playing ? 'Pause' : 'Play'}
          >
            {playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
          </button>
          <button
            onClick={skipToEnd}
            className="p-2 rounded-lg bg-surface hover:bg-surface/80 text-text-muted hover:text-text-primary transition-colors cursor-pointer"
            aria-label="Skip to end"
          >
            <SkipForward className="w-4 h-4" />
          </button>
          <button
            onClick={cycleSpeed}
            className="px-3 py-1.5 rounded-lg bg-surface text-xs font-mono font-bold text-cta hover:bg-surface/80 transition-colors cursor-pointer"
            aria-label={`Speed ${speed}x`}
          >
            {speed}×
          </button>
        </div>
      </div>

      {/* Event Cards */}
      <div className="space-y-3">
        {REPLAY_EVENTS.map((evt, idx) => {
          const Icon = evt.icon;
          const visible = idx <= currentStep;
          return (
            <div
              key={evt.id}
              className={`flex items-start gap-3 p-4 rounded-xl border transition-all duration-500 ${
                visible
                  ? 'bg-secondary border-border opacity-100 translate-y-0'
                  : 'bg-secondary/30 border-transparent opacity-30 translate-y-2'
              } ${idx === currentStep ? 'ring-1 ring-cta/40 shadow-lg shadow-cta/5' : ''}`}
            >
              <div className={`mt-0.5 w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${visible ? 'bg-cta/10' : 'bg-surface/50'}`}>
                <Icon className={`w-4 h-4 ${visible ? evt.color : 'text-text-muted/40'}`} />
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm font-medium ${visible ? 'text-text-primary' : 'text-text-muted/40'}`}>
                  {evt.title}
                </p>
                <p className={`text-xs mt-0.5 ${visible ? 'text-text-muted' : 'text-text-muted/20'}`}>
                  {evt.detail}
                </p>
              </div>
              {visible && idx === currentStep && (
                <span className="mt-1 w-2 h-2 rounded-full bg-cta animate-pulse shrink-0" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

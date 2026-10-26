import React, { useEffect, useId, useRef, useState } from 'react';

const defaultTabListClassName = 'flex border-b border-border overflow-x-auto';
const defaultTabClassName = 'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-all duration-200 cursor-pointer';

function getEnabledTabIds(tabs) {
  return tabs.filter((tab) => !tab.disabled).map((tab) => tab.id);
}

function getTabClassName(tab, selected) {
  const stateClassName = selected
    ? 'border-cta text-cta bg-cta/5'
    : 'border-transparent text-text-secondary hover:text-text-primary hover:border-border-light';
  const disabledClassName = tab.disabled ? ' opacity-50 cursor-not-allowed' : '';
  return `${defaultTabClassName} ${stateClassName}${disabledClassName}`;
}

export function Tabs({
  tabs,
  activeTab,
  onChange,
  className = '',
  tabListClassName = defaultTabListClassName,
  tabPanelClassName = 'pt-4',
  activationMode = 'automatic',
  orientation = 'horizontal',
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
}) {
  const generatedId = useId().replace(/:/g, '');
  const tabRefs = useRef(new Map());
  const enabledTabIds = getEnabledTabIds(tabs);
  const selectedTabId = enabledTabIds.includes(activeTab) ? activeTab : enabledTabIds[0];
  const [focusedTabId, setFocusedTabId] = useState(selectedTabId);

  useEffect(() => {
    if (selectedTabId !== undefined) {
      setFocusedTabId(selectedTabId);
    }
  }, [selectedTabId]);

  const focusTab = (tabId, activate) => {
    setFocusedTabId(tabId);
    tabRefs.current.get(tabId)?.focus();
    if (activate) {
      onChange(tabId);
    }
  };

  const handleKeyDown = (event, tabId) => {
    const currentIndex = enabledTabIds.indexOf(tabId);
    if (currentIndex === -1) return;

    const previousKey = orientation === 'vertical' ? 'ArrowUp' : 'ArrowLeft';
    const nextKey = orientation === 'vertical' ? 'ArrowDown' : 'ArrowRight';
    let nextIndex;

    if (event.key === previousKey) {
      nextIndex = (currentIndex - 1 + enabledTabIds.length) % enabledTabIds.length;
    } else if (event.key === nextKey) {
      nextIndex = (currentIndex + 1) % enabledTabIds.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = enabledTabIds.length - 1;
    } else if (
      activationMode === 'manual'
      && (event.key === 'Enter' || event.key === ' ')
    ) {
      event.preventDefault();
      onChange(tabId);
      return;
    } else {
      return;
    }

    event.preventDefault();
    focusTab(enabledTabIds[nextIndex], activationMode === 'automatic');
  };

  return (
    <div className={`flex flex-col ${className}`}>
      <div
        className={tabListClassName}
        role="tablist"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-orientation={orientation}
      >
        {tabs.map((tab, index) => {
          const selected = selectedTabId === tab.id;
          const tabId = `${generatedId}-tab-${index}`;
          const panelId = `${generatedId}-panel-${index}`;

          return (
            <button
              key={tab.id}
              ref={(node) => {
                if (node) {
                  tabRefs.current.set(tab.id, node);
                } else {
                  tabRefs.current.delete(tab.id);
                }
              }}
              id={tabId}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              disabled={tab.disabled}
              tabIndex={!tab.disabled && focusedTabId === tab.id ? 0 : -1}
              onClick={() => onChange(tab.id)}
              onFocus={() => setFocusedTabId(tab.id)}
              onKeyDown={(event) => handleKeyDown(event, tab.id)}
              className={getTabClassName(tab, selected)}
            >
              {tab.icon && <tab.icon aria-hidden="true" className="w-4 h-4" />}
              {tab.label}
              {tab.badge && (
                <span className="ml-1 px-1.5 py-0.5 text-[10px] font-semibold rounded-full bg-cta/15 text-cta">
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {tabs.map((tab, index) => {
        const selected = selectedTabId === tab.id;
        const tabId = `${generatedId}-tab-${index}`;
        const panelId = `${generatedId}-panel-${index}`;

        return (
          <div
            key={tab.id}
            id={panelId}
            role="tabpanel"
            aria-labelledby={tabId}
            hidden={!selected}
            className={selected ? tabPanelClassName : 'hidden'}
          >
            {selected && tab.content}
          </div>
        );
      })}
    </div>
  );
}

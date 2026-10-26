import React, { useState } from 'react';
import axeCore from 'axe-core';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Tabs } from '../Tabs';

const tabs = [
  { id: 'overview', label: 'Overview', content: <p>Overview content</p> },
  { id: 'details', label: 'Details', content: <p>Details content</p> },
  { id: 'history', label: 'History', content: <p>History content</p> },
];

function TabsHarness(props) {
  const [activeTab, setActiveTab] = useState('overview');
  return (
    <Tabs
      aria-label="Project sections"
      tabs={tabs}
      activeTab={activeTab}
      onChange={setActiveTab}
      {...props}
    />
  );
}

describe('Tabs', () => {
  it('connects tabs and panels with unique accessible relationships', () => {
    render(
      <>
        <TabsHarness />
        <TabsHarness />
      </>,
    );

    const overviewTabs = screen.getAllByRole('tab', { name: 'Overview' });
    const overviewPanels = screen.getAllByRole('tabpanel', { name: 'Overview' });

    expect(overviewTabs[0]).toHaveAttribute('aria-controls', overviewPanels[0].id);
    expect(overviewPanels[0]).toHaveAttribute('aria-labelledby', overviewTabs[0].id);
    expect(overviewTabs[0].id).not.toBe(overviewTabs[1].id);
  });

  it('uses roving focus and automatic activation for arrows, Home, and End', async () => {
    const user = userEvent.setup();
    render(<TabsHarness />);

    const overview = screen.getByRole('tab', { name: 'Overview' });
    const details = screen.getByRole('tab', { name: 'Details' });
    const history = screen.getByRole('tab', { name: 'History' });

    overview.focus();
    await user.keyboard('{ArrowRight}');
    expect(details).toHaveFocus();
    expect(details).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel', { name: 'Details' })).toHaveTextContent('Details content');

    await user.keyboard('{End}');
    expect(history).toHaveFocus();
    expect(history).toHaveAttribute('tabindex', '0');

    await user.keyboard('{ArrowRight}');
    expect(overview).toHaveFocus();

    await user.keyboard('{End}{Home}');
    expect(overview).toHaveFocus();
    expect(overview).toHaveAttribute('aria-selected', 'true');
  });

  it('moves focus without activation in manual mode until Enter or Space', async () => {
    const user = userEvent.setup();
    render(<TabsHarness activationMode="manual" />);

    const overview = screen.getByRole('tab', { name: 'Overview' });
    const details = screen.getByRole('tab', { name: 'Details' });

    overview.focus();
    await user.keyboard('{ArrowRight}');
    expect(details).toHaveFocus();
    expect(overview).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{Enter}');
    expect(details).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowLeft}{ }');
    expect(overview).toHaveAttribute('aria-selected', 'true');
  });

  it('skips disabled tabs during keyboard navigation', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Tabs
        aria-label="Project sections"
        tabs={[
          tabs[0],
          { ...tabs[1], disabled: true },
          tabs[2],
        ]}
        activeTab="overview"
        onChange={onChange}
      />,
    );

    screen.getByRole('tab', { name: 'Overview' }).focus();
    await user.keyboard('{ArrowRight}');

    expect(screen.getByRole('tab', { name: 'History' })).toHaveFocus();
    expect(onChange).toHaveBeenCalledWith('history');
  });

  it('has no axe accessibility violations', async () => {
    const { container } = render(<TabsHarness />);
    const results = await axeCore.run(container);

    expect(results.violations).toEqual([]);
  });
});

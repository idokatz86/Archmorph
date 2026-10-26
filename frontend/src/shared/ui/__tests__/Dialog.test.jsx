import React, { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dialog, DialogTitle } from '../Dialog';

const dialogClasses = {
  containerClassName: 'fixed inset-0',
  backdropClassName: 'fixed inset-0',
  className: 'relative',
};

function DialogHarness() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open settings</button>
      <Dialog open={open} onClose={() => setOpen(false)} {...dialogClasses}>
        <DialogTitle>Settings</DialogTitle>
        <button type="button">First action</button>
        <button type="button" onClick={() => setOpen(false)}>Last action</button>
      </Dialog>
    </>
  );
}

describe('Dialog', () => {
  it('creates a unique accessible-name relationship for each dialog', () => {
    render(
      <>
        <Dialog open onClose={vi.fn()} {...dialogClasses}>
          <DialogTitle>First dialog</DialogTitle>
          <button type="button">Close first</button>
        </Dialog>
        <Dialog open onClose={vi.fn()} {...dialogClasses}>
          <DialogTitle>Second dialog</DialogTitle>
          <button type="button">Close second</button>
        </Dialog>
      </>,
    );

    const first = screen.getByRole('dialog', { name: 'First dialog' });
    const second = screen.getByRole('dialog', { name: 'Second dialog' });
    expect(first.getAttribute('aria-labelledby')).not.toBe(second.getAttribute('aria-labelledby'));
  });

  it('traps focus, closes on Escape, and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);

    const opener = screen.getByRole('button', { name: 'Open settings' });
    await user.click(opener);

    const first = screen.getByRole('button', { name: 'First action' });
    const last = screen.getByRole('button', { name: 'Last action' });
    await waitFor(() => expect(first).toHaveFocus());

    last.focus();
    await user.tab();
    expect(first).toHaveFocus();

    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Settings' })).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('keeps focus inside a dialog without enabled focusable descendants', async () => {
    const user = userEvent.setup();

    function EmptyDialogHarness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Open status</button>
          <Dialog open={open} onClose={() => setOpen(false)} {...dialogClasses}>
            <DialogTitle>Status</DialogTitle>
            <p>No actions are currently available.</p>
            <button type="button" disabled>Unavailable</button>
          </Dialog>
        </>
      );
    }

    render(<EmptyDialogHarness />);
    const opener = screen.getByRole('button', { name: 'Open status' });
    await user.click(opener);

    const dialog = screen.getByRole('dialog', { name: 'Status' });
    await waitFor(() => expect(dialog).toHaveFocus());

    await user.tab();
    expect(dialog).toHaveFocus();
    await user.tab({ shift: true });
    expect(dialog).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(dialog).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('locks scrolling and closes from the backdrop', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    document.body.style.overflow = 'auto';

    const { unmount } = render(
      <Dialog
        open
        onClose={onClose}
        backdropTestId="dialog-backdrop"
        {...dialogClasses}
      >
        <DialogTitle>Settings</DialogTitle>
        <button type="button">Close</button>
      </Dialog>,
    );

    expect(document.body.style.overflow).toBe('hidden');
    await user.click(screen.getByTestId('dialog-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();
    expect(document.body.style.overflow).toBe('auto');
    document.body.style.overflow = '';
  });
});

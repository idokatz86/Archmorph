import React, { useState } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import useFocusTrap from '../useFocusTrap';

function FocusTrapHarness() {
  const [open, setOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const trapRef = useFocusTrap(open);
  const close = () => setOpen(false);

  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      {open && (
        <div
          ref={trapRef}
          role="dialog"
          aria-modal="true"
          onClick={close}
          onKeyDown={(event) => {
            if (event.key === 'Escape') close();
          }}
        >
          <div onClick={(event) => event.stopPropagation()}>
            <button type="button" onClick={close}>Close</button>
            <button
              type="button"
              onClick={() => {
                setSubmitted(true);
                close();
              }}
            >
              Submit
            </button>
          </div>
        </div>
      )}
      {submitted && <p>Submitted</p>}
    </div>
  );
}

async function expectFocusRestoredToOpener() {
  await waitFor(() => expect(screen.getByRole('button', { name: /open dialog/i })).toHaveFocus());
}

describe('useFocusTrap', () => {
  it('restores focus to opener when closed with Escape', async () => {
    const user = userEvent.setup();
    render(<FocusTrapHarness />);

    await user.click(screen.getByRole('button', { name: /open dialog/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /^close$/i })).toHaveFocus());
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await expectFocusRestoredToOpener();
  });

  it('restores focus to opener when closed with the close button', async () => {
    const user = userEvent.setup();
    render(<FocusTrapHarness />);

    await user.click(screen.getByRole('button', { name: /open dialog/i }));
    await user.click(screen.getByRole('button', { name: /^close$/i }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await expectFocusRestoredToOpener();
  });

  it('restores focus to opener when closed from the backdrop', async () => {
    const user = userEvent.setup();
    render(<FocusTrapHarness />);

    await user.click(screen.getByRole('button', { name: /open dialog/i }));
    await user.click(screen.getByRole('dialog'));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await expectFocusRestoredToOpener();
  });

  it('restores focus to opener after submit-driven close', async () => {
    const user = userEvent.setup();
    render(<FocusTrapHarness />);

    await user.click(screen.getByRole('button', { name: /open dialog/i }));
    await user.click(screen.getByRole('button', { name: /submit/i }));

    expect(screen.getByText('Submitted')).toBeInTheDocument();
    await expectFocusRestoredToOpener();
  });
});
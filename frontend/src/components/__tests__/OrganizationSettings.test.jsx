import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import OrganizationSettings from '../OrganizationSettings';

vi.mock('../../services/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import api from '../../services/apiClient';

describe('OrganizationSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    api.get.mockReturnValue(new Promise(() => {}));
    render(<OrganizationSettings />);
    expect(screen.getByText(/Loading organizations/)).toBeInTheDocument();
  });

  it('shows empty state when no organizations', async () => {
    api.get.mockResolvedValue({ organizations: [] });

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText(/No organizations yet/)).toBeInTheDocument();
    });
  });

  it('shows organization list when orgs exist', async () => {
    api.get
      .mockResolvedValueOnce({
        organizations: [
          { org_id: 'org-1', name: 'Test Org', plan: 'pro' },
        ],
      })
      .mockResolvedValueOnce({
        members: [
          { user_id: 'user-1', display_name: 'Alice', email: 'alice@test.com', role: 'owner' },
        ],
      });

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText('Test Org')).toBeInTheDocument();
    });
  });

  it('shows "New Organization" button', async () => {
    api.get.mockResolvedValue({ organizations: [] });

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText('New Organization')).toBeInTheDocument();
    });
  });

  it('shows Members section when an org is selected', async () => {
    api.get
      .mockResolvedValueOnce({
        organizations: [
          { org_id: 'org-1', name: 'Test Org', plan: 'free' },
        ],
      })
      .mockResolvedValueOnce({
        members: [
          { user_id: 'user-1', display_name: 'Alice', email: 'alice@test.com', role: 'owner' },
        ],
      });

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText('Members')).toBeInTheDocument();
    });
  });

  it('shows Invite Member section', async () => {
    api.get
      .mockResolvedValueOnce({
        organizations: [
          { org_id: 'org-1', name: 'Test Org', plan: 'free' },
        ],
      })
      .mockResolvedValueOnce({
        members: [],
      });

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText('Invite Member')).toBeInTheDocument();
    });
  });

  it('shows error state on API failure', async () => {
    api.get.mockRejectedValue(new Error('Network failure'));

    render(<OrganizationSettings />);

    await vi.waitFor(() => {
      expect(screen.getByText('Network failure')).toBeInTheDocument();
    });
  });
});

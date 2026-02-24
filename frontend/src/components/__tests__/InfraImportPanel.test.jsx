import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import InfraImportPanel from '../InfraImportPanel';

vi.mock('../../services/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from '../../services/apiClient';

describe('InfraImportPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the import panel heading', () => {
    render(<InfraImportPanel />);
    expect(screen.getByText('Import Infrastructure')).toBeInTheDocument();
  });

  it('renders format selector with all options', () => {
    render(<InfraImportPanel />);
    expect(screen.getByText('Auto-detect')).toBeInTheDocument();
    expect(screen.getByText('Terraform State')).toBeInTheDocument();
    expect(screen.getByText('Terraform HCL')).toBeInTheDocument();
    expect(screen.getByText('CloudFormation')).toBeInTheDocument();
    expect(screen.getByText('ARM Template')).toBeInTheDocument();
    expect(screen.getByText('Kubernetes')).toBeInTheDocument();
    expect(screen.getByText('Docker Compose')).toBeInTheDocument();
  });

  it('renders upload and paste buttons', () => {
    render(<InfraImportPanel />);
    expect(screen.getByText('Upload File')).toBeInTheDocument();
    expect(screen.getByText('Paste from Clipboard')).toBeInTheDocument();
  });

  it('renders textarea for content input', () => {
    render(<InfraImportPanel />);
    expect(screen.getByPlaceholderText(/paste your Terraform/i)).toBeInTheDocument();
  });

  it('has disabled Import button when content is empty', () => {
    render(<InfraImportPanel />);
    const btn = screen.getByText('Import & Analyze');
    expect(btn.closest('button')).toBeDisabled();
  });

  it('enables Import button when content is entered', () => {
    render(<InfraImportPanel />);
    const textarea = screen.getByPlaceholderText(/paste your Terraform/i);
    fireEvent.change(textarea, { target: { value: 'resource "aws_s3_bucket" {}' } });
    const btn = screen.getByText('Import & Analyze');
    expect(btn.closest('button')).not.toBeDisabled();
  });

  it('calls api.post on import', async () => {
    api.post.mockResolvedValue({
      analysis: { mappings: [], zones: [] },
      detected_format: 'terraform_hcl',
    });

    render(<InfraImportPanel />);
    const textarea = screen.getByPlaceholderText(/paste your Terraform/i);
    fireEvent.change(textarea, { target: { value: 'resource "aws_s3" {}' } });
    fireEvent.click(screen.getByText('Import & Analyze'));

    expect(api.post).toHaveBeenCalledWith('/import/infrastructure', {
      content: 'resource "aws_s3" {}',
      format: undefined,
    });
  });

  it('shows success state after import', async () => {
    api.post.mockResolvedValue({
      analysis: {
        mappings: [
          { source_service: 'S3', azure_service: 'Blob Storage', confidence: 0.95 },
        ],
        zones: [{ name: 'Storage' }],
      },
      detected_format: 'terraform_hcl',
    });

    render(<InfraImportPanel />);
    const textarea = screen.getByPlaceholderText(/paste your Terraform/i);
    fireEvent.change(textarea, { target: { value: 'resource "aws_s3" {}' } });
    fireEvent.click(screen.getByText('Import & Analyze'));

    await vi.waitFor(() => {
      expect(screen.getByText('Import Successful')).toBeInTheDocument();
    });
  });

  it('shows error state on import failure', async () => {
    api.post.mockRejectedValue(new Error('Parse failed'));

    render(<InfraImportPanel />);
    const textarea = screen.getByPlaceholderText(/paste your Terraform/i);
    fireEvent.change(textarea, { target: { value: 'invalid content' } });
    fireEvent.click(screen.getByText('Import & Analyze'));

    await vi.waitFor(() => {
      expect(screen.getByText('Parse failed')).toBeInTheDocument();
    });
  });

  it('calls onImportComplete callback on success', async () => {
    const onComplete = vi.fn();
    const mockResult = {
      analysis: { mappings: [], zones: [] },
      detected_format: 'auto',
    };
    api.post.mockResolvedValue(mockResult);

    render(<InfraImportPanel onImportComplete={onComplete} />);
    const textarea = screen.getByPlaceholderText(/paste your Terraform/i);
    fireEvent.change(textarea, { target: { value: 'content' } });
    fireEvent.click(screen.getByText('Import & Analyze'));

    await vi.waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith(mockResult);
    });
  });
});

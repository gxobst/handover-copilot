import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AdminPanel, AdminPanelTrigger } from './AdminPanel';
import { adminApi } from '../services';
import { ApiError } from '../services/errors';
import type { AdminSettingsResponse } from '../types/api.ts';

describe('AdminPanel Component', () => {
  const validToken = 'dev-admin-secret-key-12345';

  const defaultSettings: AdminSettingsResponse = {
    activeModel: 'google/gemini-3.5-flash-lite',
    fallbackModel: 'google/gemini-3.1-flash-lite',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  describe('Modal Presentation & Accessibility (AC-1)', () => {
    it('renders dialog with accessible attributes when isOpen is true', () => {
      render(<AdminPanel isOpen={true} />);

      const dialog = screen.getByRole('dialog');
      expect(dialog).toBeInTheDocument();
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(dialog).toHaveAttribute('aria-labelledby', 'admin-panel-title');
      expect(screen.getByText('Admin Configuration Panel')).toBeInTheDocument();
    });

    it('returns null and does not render when isOpen is false', () => {
      render(<AdminPanel isOpen={false} />);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('invokes onClose when clicking the close button', async () => {
      const handleClose = vi.fn();
      render(<AdminPanel isOpen={true} onClose={handleClose} />);

      const closeButton = screen.getByRole('button', { name: /close admin panel/i });
      fireEvent.click(closeButton);

      expect(handleClose).toHaveBeenCalledTimes(1);
    });

    it('invokes onClose when pressing Escape key', () => {
      const handleClose = vi.fn();
      render(<AdminPanel isOpen={true} onClose={handleClose} />);

      fireEvent.keyDown(window, { key: 'Escape' });
      expect(handleClose).toHaveBeenCalledTimes(1);
    });

    it('invokes onClose when clicking the backdrop overlay', () => {
      const handleClose = vi.fn();
      render(<AdminPanel isOpen={true} onClose={handleClose} />);

      const backdrop = screen.getByTestId('admin-panel-backdrop');
      fireEvent.click(backdrop);

      expect(handleClose).toHaveBeenCalledTimes(1);
    });

    it('does not invoke onClose when clicking inside the dialog card', () => {
      const handleClose = vi.fn();
      render(<AdminPanel isOpen={true} onClose={handleClose} />);

      const dialog = screen.getByRole('dialog');
      fireEvent.click(dialog);

      expect(handleClose).not.toHaveBeenCalled();
    });

    it('renders AdminPanelTrigger button and handles onClick', () => {
      const handleClick = vi.fn();
      render(<AdminPanelTrigger onClick={handleClick} />);

      const trigger = screen.getByRole('button', { name: /admin settings/i });
      expect(trigger).toBeInTheDocument();
      expect(trigger).toHaveTextContent('Admin Settings');

      fireEvent.click(trigger);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it('applies custom className to AdminPanel and AdminPanelTrigger', () => {
      render(<AdminPanel isOpen={true} className="custom-panel-class" />);
      const dialog = screen.getByRole('dialog');
      expect(dialog.className).toContain('custom-panel-class');

      render(<AdminPanelTrigger className="custom-trigger-class" />);
      const trigger = screen.getAllByRole('button', { name: /admin settings/i })[0];
      expect(trigger.className).toContain('custom-trigger-class');
    });
  });

  describe('Locked State & Authentication Management (AC-2)', () => {
    it('renders locked state when no admin token is provided', () => {
      render(<AdminPanel />);

      expect(screen.getByText('Admin Authentication Required')).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText('Enter admin token (e.g. dev-admin-secret-key-12345)')
      ).toBeInTheDocument();

      const unlockButton = screen.getByRole('button', { name: /unlock/i });
      expect(unlockButton).toBeInTheDocument();
      expect(unlockButton).toBeDisabled();

      // Does not show model configuration cards or update form
      expect(screen.queryByText('Current Model Configuration')).not.toBeInTheDocument();
      expect(screen.queryByText('Reconfigure Model Routing')).not.toBeInTheDocument();
    });

    it('enables unlock button when token input has non-whitespace characters', () => {
      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      const unlockButton = screen.getByRole('button', { name: /unlock/i });

      fireEvent.change(tokenInput, { target: { value: '   ' } });
      expect(unlockButton).toBeDisabled();

      fireEvent.change(tokenInput, { target: { value: 'my-admin-token' } });
      expect(unlockButton).not.toBeDisabled();
    });

    it('toggles token masking between password and text using Eye/EyeOff toggle', () => {
      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      expect(tokenInput).toHaveAttribute('type', 'password');

      const toggleButton = screen.getByRole('button', { name: /show admin token/i });
      fireEvent.click(toggleButton);

      expect(tokenInput).toHaveAttribute('type', 'text');
      expect(screen.getByRole('button', { name: /hide admin token/i })).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /hide admin token/i }));
      expect(tokenInput).toHaveAttribute('type', 'password');
    });
  });

  describe('Inspecting Model Settings (GET /api/admin/settings)', () => {
    it('calls adminApi.getSettings on unlock and renders model configuration cards on 200 OK', async () => {
      const getSpy = vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);

      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      fireEvent.change(tokenInput, { target: { value: validToken } });

      const unlockButton = screen.getByRole('button', { name: /unlock/i });
      fireEvent.click(unlockButton);

      expect(getSpy).toHaveBeenCalledWith(validToken);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      // Model configuration cards rendered
      expect(screen.getByText('Current Model Configuration')).toBeInTheDocument();
      expect(screen.getByText(defaultSettings.activeModel)).toBeInTheDocument();
      expect(screen.getByText(defaultSettings.fallbackModel)).toBeInTheDocument();

      // Form inputs pre-filled
      const activeInput = screen.getByLabelText('Active Model');
      const fallbackInput = screen.getByLabelText('Fallback Model');
      expect(activeInput).toHaveValue(defaultSettings.activeModel);
      expect(fallbackInput).toHaveValue(defaultSettings.fallbackModel);
    });

    it('automatically fetches settings on mount when initialToken prop is provided', async () => {
      const getSpy = vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);

      render(<AdminPanel initialToken={validToken} />);

      expect(getSpy).toHaveBeenCalledWith(validToken);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      expect(screen.getByText(defaultSettings.activeModel)).toBeInTheDocument();
      expect(screen.getByText(defaultSettings.fallbackModel)).toBeInTheDocument();
    });

    it('displays 401 Unauthorized error banner with RFC 9457 detail and traceId on getSettings failure', async () => {
      const apiError = new ApiError(401, 'Unauthorized', {
        type: 'https://api.shift-copilot.example.com/errors/unauthorized',
        title: 'Unauthorized',
        status: 401,
        detail: 'Invalid admin bearer token supplied.',
        traceId: 'tr-401-auth-failed',
      });
      vi.spyOn(adminApi, 'getSettings').mockRejectedValue(apiError);

      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      fireEvent.change(tokenInput, { target: { value: 'wrong-token' } });

      const unlockButton = screen.getByRole('button', { name: /unlock/i });
      fireEvent.click(unlockButton);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(
        screen.getByText('Unauthorized: Invalid or missing admin token')
      ).toBeInTheDocument();
      expect(screen.getByText('Invalid admin bearer token supplied.')).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-401-auth-failed')).toBeInTheDocument();

      // Stays in locked state
      expect(screen.getByText('Admin Authentication Required')).toBeInTheDocument();
      expect(screen.queryByText('Current Model Configuration')).not.toBeInTheDocument();
    });
  });

  describe('Model Name Validation Rules (AC-10, plan.md §8)', () => {
    beforeEach(async () => {
      vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);
    });

    it('rejects invalid model names with spaces and special characters', async () => {
      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const saveButton = screen.getByRole('button', { name: /save changes/i });

      // Special character '@' and '!'
      fireEvent.change(activeInput, { target: { value: 'model@test!' } });
      expect(
        screen.getByText(
          "Model name contains invalid characters. Only alphanumeric, '.', '_', '/', and '-' are allowed."
        )
      ).toBeInTheDocument();
      expect(saveButton).toBeDisabled();

      // Space
      fireEvent.change(activeInput, { target: { value: 'google gemini 3.5' } });
      expect(
        screen.getByText(
          "Model name contains invalid characters. Only alphanumeric, '.', '_', '/', and '-' are allowed."
        )
      ).toBeInTheDocument();
      expect(saveButton).toBeDisabled();

      // Empty string
      fireEvent.change(activeInput, { target: { value: '   ' } });
      expect(screen.getByText('Model name is required.')).toBeInTheDocument();
      expect(saveButton).toBeDisabled();

      // Over 128 characters
      const tooLongName = 'a'.repeat(129);
      fireEvent.change(activeInput, { target: { value: tooLongName } });
      expect(
        screen.getByText('Model name cannot exceed 128 characters.')
      ).toBeInTheDocument();
      expect(saveButton).toBeDisabled();
    });

    it('accepts retired model names without allowlist rejection (plan.md §8)', async () => {
      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const saveButton = screen.getByRole('button', { name: /save changes/i });

      fireEvent.change(activeInput, {
        target: { value: 'google/gemini-2.5-flash-lite-retired' },
      });

      expect(
        screen.queryByText(/model name contains invalid characters/i)
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/model name is required/i)).not.toBeInTheDocument();
      expect(saveButton).not.toBeDisabled();
    });

    it('disables save button if neither active nor fallback model has changed', async () => {
      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      expect(saveButton).toBeDisabled();
    });
  });

  describe('Updating Model Settings (PUT /api/admin/settings)', () => {
    beforeEach(async () => {
      vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);
    });

    it('submitting only activeModel sends single field update and displays updated badge on 200 response', async () => {
      const updatedResponse: AdminSettingsResponse = {
        activeModel: 'google/gemini-3.5-pro',
        fallbackModel: defaultSettings.fallbackModel,
      };

      const updateSpy = vi
        .spyOn(adminApi, 'updateSettings')
        .mockResolvedValue(updatedResponse);

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      fireEvent.change(activeInput, { target: { value: 'google/gemini-3.5-pro' } });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      expect(saveButton).not.toBeDisabled();

      fireEvent.click(saveButton);

      expect(updateSpy).toHaveBeenCalledWith(
        { activeModel: 'google/gemini-3.5-pro' },
        validToken
      );

      await waitFor(() => {
        expect(
          screen.getByText(
            'Model settings updated successfully. Takes effect on next report generation.'
          )
        ).toBeInTheDocument();
      });

      // Active model card displays new value
      expect(screen.getByText('google/gemini-3.5-pro')).toBeInTheDocument();
      // Form dirty state cleared: save button is disabled again
      expect(saveButton).toBeDisabled();
    });

    it('submitting both active and fallback models calls updateSettings and shows loading spinner', async () => {
      const updatedResponse: AdminSettingsResponse = {
        activeModel: 'google/gemini-2.5-flash-lite-retired',
        fallbackModel: 'google/gemini-3.5-flash-lite',
      };

      const updateSpy = vi
        .spyOn(adminApi, 'updateSettings')
        .mockResolvedValue(updatedResponse);

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const fallbackInput = screen.getByLabelText('Fallback Model');

      fireEvent.change(activeInput, {
        target: { value: 'google/gemini-2.5-flash-lite-retired' },
      });
      fireEvent.change(fallbackInput, {
        target: { value: 'google/gemini-3.5-flash-lite' },
      });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      fireEvent.click(saveButton);

      expect(updateSpy).toHaveBeenCalledWith(
        {
          activeModel: 'google/gemini-2.5-flash-lite-retired',
          fallbackModel: 'google/gemini-3.5-flash-lite',
        },
        validToken
      );

      await waitFor(() => {
        expect(
          screen.getByText(
            'Model settings updated successfully. Takes effect on next report generation.'
          )
        ).toBeInTheDocument();
      });

      expect(screen.getByText('google/gemini-2.5-flash-lite-retired')).toBeInTheDocument();
      expect(screen.getByText('google/gemini-3.5-flash-lite')).toBeInTheDocument();
    });

    it('displays 401 Unauthorized error banner with copyable traceId on updateSettings failure', async () => {
      const apiError = new ApiError(401, 'Unauthorized', {
        type: 'https://api.shift-copilot.example.com/errors/unauthorized',
        title: 'Unauthorized',
        status: 401,
        detail: 'Admin session expired or token revoked.',
        traceId: 'tr-update-401',
      });

      vi.spyOn(adminApi, 'updateSettings').mockRejectedValue(apiError);

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      fireEvent.change(activeInput, { target: { value: 'google/gemini-3.5-pro' } });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(
        screen.getByText('Unauthorized: Invalid or missing admin token')
      ).toBeInTheDocument();
      expect(
        screen.getByText('Admin session expired or token revoked.')
      ).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-update-401')).toBeInTheDocument();
    });

    it('displays 422 Unprocessable Entity error banner on updateSettings validation error', async () => {
      const apiError = new ApiError(422, 'Unprocessable Entity', {
        type: 'https://api.shift-copilot.example.com/errors/validation',
        title: 'Validation Error',
        status: 422,
        detail: 'Active model is not supported by the backend gateway.',
        traceId: 'tr-update-422',
      });

      vi.spyOn(adminApi, 'updateSettings').mockRejectedValue(apiError);

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      fireEvent.change(activeInput, { target: { value: 'unsupported-gateway-model' } });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(
        screen.getByText('Validation Error: Invalid model configuration')
      ).toBeInTheDocument();
      expect(
        screen.getByText('Active model is not supported by the backend gateway.')
      ).toBeInTheDocument();
      expect(screen.getByText('Trace ID: tr-update-422')).toBeInTheDocument();
    });

    it('allows retry on 500 server error', async () => {
      const updateSpy = vi
        .spyOn(adminApi, 'updateSettings')
        .mockRejectedValueOnce(
          new ApiError(500, 'Server Error', {
            type: 'about:blank',
            title: 'Server Error',
            status: 500,
            detail: 'Database write timed out.',
            traceId: 'tr-500-retry',
          })
        )
        .mockResolvedValueOnce({
          activeModel: 'google/gemini-3.5-pro',
          fallbackModel: defaultSettings.fallbackModel,
        });

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      fireEvent.change(activeInput, { target: { value: 'google/gemini-3.5-pro' } });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      fireEvent.click(saveButton);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(updateSpy).toHaveBeenCalledTimes(1);

      // Click Retry
      const retryButton = screen.getByRole('button', { name: /retry/i });
      fireEvent.click(retryButton);

      await waitFor(() => {
        expect(
          screen.getByText(
            'Model settings updated successfully. Takes effect on next report generation.'
          )
        ).toBeInTheDocument();
      });

      expect(updateSpy).toHaveBeenCalledTimes(2);
    });
  });

  describe('Presets & Reset Controls', () => {
    beforeEach(async () => {
      vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);
    });

    it('populates form inputs with default model strings on "Default Models" preset click without auto-submitting', async () => {
      const updateSpy = vi.spyOn(adminApi, 'updateSettings');

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const fallbackInput = screen.getByLabelText('Fallback Model');

      // First change to custom values
      fireEvent.change(activeInput, { target: { value: 'custom/model-a' } });
      fireEvent.change(fallbackInput, { target: { value: 'custom/model-b' } });

      const defaultPresetButton = screen.getByRole('button', { name: /default models/i });
      fireEvent.click(defaultPresetButton);

      expect(activeInput).toHaveValue('google/gemini-3.5-flash-lite');
      expect(fallbackInput).toHaveValue('google/gemini-3.1-flash-lite');
      expect(updateSpy).not.toHaveBeenCalled();
    });

    it('populates form inputs with retired model string on "Simulate Incident" preset click without auto-submitting', async () => {
      const updateSpy = vi.spyOn(adminApi, 'updateSettings');

      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const fallbackInput = screen.getByLabelText('Fallback Model');

      const incidentPresetButton = screen.getByRole('button', {
        name: /simulate incident/i,
      });
      fireEvent.click(incidentPresetButton);

      expect(activeInput).toHaveValue('google/gemini-2.5-flash-lite-retired');
      expect(fallbackInput).toHaveValue('google/gemini-3.5-flash-lite');
      expect(updateSpy).not.toHaveBeenCalled();

      // Save button is enabled
      const saveButton = screen.getByRole('button', { name: /save changes/i });
      expect(saveButton).not.toBeDisabled();
    });

    it('reverts form inputs to saved settings on Reset button click', async () => {
      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const activeInput = screen.getByLabelText('Active Model');
      const fallbackInput = screen.getByLabelText('Fallback Model');

      fireEvent.change(activeInput, { target: { value: 'temporary-active' } });
      fireEvent.change(fallbackInput, { target: { value: 'temporary-fallback' } });

      const resetButton = screen.getByRole('button', { name: /reset/i });
      expect(resetButton).not.toBeDisabled();

      fireEvent.click(resetButton);

      expect(activeInput).toHaveValue(defaultSettings.activeModel);
      expect(fallbackInput).toHaveValue(defaultSettings.fallbackModel);
      expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
    });
  });

  describe('Lock / Clear Token & Security', () => {
    beforeEach(async () => {
      vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);
    });

    it('clicking "Lock / Clear Token" clears state and returns to locked screen', async () => {
      render(<AdminPanel initialToken={validToken} />);

      await waitFor(() => {
        expect(screen.getByText('Authenticated as Admin')).toBeInTheDocument();
      });

      const clearTokenButton = screen.getByRole('button', {
        name: /lock \/ clear token/i,
      });
      fireEvent.click(clearTokenButton);

      expect(screen.getByText('Admin Authentication Required')).toBeInTheDocument();
      expect(screen.queryByText('Current Model Configuration')).not.toBeInTheDocument();
      expect(screen.queryByText('Reconfigure Model Routing')).not.toBeInTheDocument();

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      expect(tokenInput).toHaveValue('');
    });

    it('copies trace ID to clipboard when copy button is clicked', async () => {
      vi.useFakeTimers();
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      vi.spyOn(adminApi, 'getSettings').mockRejectedValue(
        new ApiError(401, 'Unauthorized', {
          type: 'about:blank',
          title: 'Unauthorized',
          status: 401,
          detail: 'Auth failed.',
          traceId: 'tr-clipboard-admin-99',
        })
      );

      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      fireEvent.change(tokenInput, { target: { value: 'bad-token' } });

      const unlockButton = screen.getByRole('button', { name: /unlock/i });
      fireEvent.click(unlockButton);

      await act(async () => {
        await Promise.resolve();
      });

      const copyButton = screen.getByRole('button', { name: /copy trace id/i });
      expect(copyButton).toBeInTheDocument();
      expect(copyButton).toHaveTextContent('Copy');

      await act(async () => {
        fireEvent.click(copyButton);
      });

      expect(writeTextMock).toHaveBeenCalledWith('tr-clipboard-admin-99');
      expect(copyButton).toHaveTextContent('Copied!');

      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(copyButton).toHaveTextContent('Copy');
    });
  });

  describe('Cold-Start Notification (design-system.md §3.3)', () => {
    it('displays cold-start notification when getSettings takes longer than 3 seconds', async () => {
      vi.useFakeTimers();

      let resolveSettings!: (value: AdminSettingsResponse) => void;
      const delayedPromise = new Promise<AdminSettingsResponse>((res) => {
        resolveSettings = res;
      });

      vi.spyOn(adminApi, 'getSettings').mockReturnValue(delayedPromise);

      render(<AdminPanel />);

      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      fireEvent.change(tokenInput, { target: { value: validToken } });

      const unlockButton = screen.getByRole('button', { name: /unlock/i });
      fireEvent.click(unlockButton);

      // Advance by 2900ms: not yet shown
      act(() => {
        vi.advanceTimersByTime(2900);
      });
      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();

      // Advance past 3000ms: cold start banner appears
      act(() => {
        vi.advanceTimersByTime(200);
      });
      expect(
        screen.getByText(
          'Waking up the database — the first request after an idle period may take up to 20 s.'
        )
      ).toBeInTheDocument();

      // Resolve the request: notification dismisses
      await act(async () => {
        resolveSettings(defaultSettings);
        await Promise.resolve();
      });

      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();
    });

    it('displays cold-start notification when updateSettings takes longer than 3 seconds', async () => {
      vi.useFakeTimers();

      vi.spyOn(adminApi, 'getSettings').mockResolvedValue(defaultSettings);

      let resolveUpdate!: (value: AdminSettingsResponse) => void;
      const delayedUpdatePromise = new Promise<AdminSettingsResponse>((res) => {
        resolveUpdate = res;
      });

      vi.spyOn(adminApi, 'updateSettings').mockReturnValue(delayedUpdatePromise);

      render(<AdminPanel initialToken={validToken} />);

      await act(async () => {
        await Promise.resolve();
      });

      const activeInput = screen.getByLabelText('Active Model');
      fireEvent.change(activeInput, { target: { value: 'google/gemini-3.5-pro' } });

      const saveButton = screen.getByRole('button', { name: /save changes/i });
      fireEvent.click(saveButton);

      // Advance past 3000ms
      act(() => {
        vi.advanceTimersByTime(3100);
      });

      expect(
        screen.getByText(
          'Waking up the database — the first request after an idle period may take up to 20 s.'
        )
      ).toBeInTheDocument();

      // Resolve update request
      await act(async () => {
        resolveUpdate({
          activeModel: 'google/gemini-3.5-pro',
          fallbackModel: defaultSettings.fallbackModel,
        });
        await Promise.resolve();
      });

      expect(
        screen.queryByText(/waking up the database/i)
      ).not.toBeInTheDocument();
    });
  });

  describe('Focus Trapping (AC-1)', () => {
    it('traps Tab focus inside the modal dialog and cycles around', async () => {
      const user = userEvent.setup();
      render(<AdminPanel />);

      const closeButton = screen.getByRole('button', { name: /close admin panel/i });
      const tokenInput = screen.getByPlaceholderText(
        'Enter admin token (e.g. dev-admin-secret-key-12345)'
      );
      const eyeButton = screen.getByRole('button', { name: /show admin token/i });

      // Focus close button first
      closeButton.focus();
      expect(document.activeElement).toBe(closeButton);

      // Press Tab -> focus moves to tokenInput
      await user.tab();
      expect(document.activeElement).toBe(tokenInput);

      // Press Tab -> focus moves to eyeButton
      await user.tab();
      expect(document.activeElement).toBe(eyeButton);

      // Press Tab on eyeButton (last enabled element) -> wraps to closeButton
      await user.tab();
      expect(document.activeElement).toBe(closeButton);

      // Press Shift+Tab on closeButton (first element) -> wraps to eyeButton (last element)
      await user.tab({ shift: true });
      expect(document.activeElement).toBe(eyeButton);
    });
  });
});

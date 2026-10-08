/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import LoginPage from '@/app/login/page';
import RegisterPage from '@/app/register/page';
import ForgotPasswordPage from '@/app/forgot-password/page';
import ResetPasswordPage from '@/app/reset-password/page';
import { AuthProvider } from '@/lib/auth';

const mockPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => mockSearchParams
}));

describe('Auth Pages', () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockSearchParams = new URLSearchParams();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('LoginPage (/login)', () => {
    it('renders login form elements with username and password inputs', () => {
      render(<LoginPage />);

      expect(screen.getByRole('heading', { name: /Sign In to Carefold/i })).toBeInTheDocument();
      expect(screen.getByTestId('login-username-input')).toBeInTheDocument();
      expect(screen.getByTestId('login-password-input')).toBeInTheDocument();
      expect(screen.getByTestId('login-submit-btn')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Forgot password\?/i })).toBeInTheDocument();
    });

    it('toggles password visibility when eye button is clicked', () => {
      render(<LoginPage />);
      const passwordInput = screen.getByTestId('login-password-input');
      const toggleBtn = screen.getByTestId('toggle-password-visibility');

      expect(passwordInput).toHaveAttribute('type', 'password');
      fireEvent.click(toggleBtn);
      expect(passwordInput).toHaveAttribute('type', 'text');
      fireEvent.click(toggleBtn);
      expect(passwordInput).toHaveAttribute('type', 'password');
    });

    it('submits login request and handles error alert on failure', async () => {
      vi.mocked(fetch).mockImplementation(async (url: any) => {
        const urlStr = String(url);
        if (urlStr.includes('/api/auth/providers')) {
          return {
            ok: true,
            json: async () => ({ active_provider: 'local', sso_providers: [], registration_enabled: true })
          } as any;
        }
        if (urlStr.includes('/api/auth/me')) {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        if (urlStr.includes('/api/auth/login')) {
          return {
            ok: false,
            status: 401,
            json: async () => ({ detail: 'Invalid credentials provided' })
          } as any;
        }
        return { ok: true, json: async () => ({}) } as any;
      });

      render(
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      );

      fireEvent.change(screen.getByTestId('login-username-input'), {
        target: { value: 'bad_user' }
      });
      fireEvent.change(screen.getByTestId('login-password-input'), {
        target: { value: 'wrong_password' }
      });

      fireEvent.click(screen.getByTestId('login-submit-btn'));

      await waitFor(() => {
        expect(screen.getByTestId('login-error-alert')).toBeInTheDocument();
      });
      expect(screen.getByTestId('login-error-alert')).toHaveTextContent(/Invalid credentials provided/i);
    });
  });

  describe('RegisterPage (/register)', () => {
    it('renders registration form elements with live strength indicator', () => {
      render(<RegisterPage />);

      expect(screen.getByRole('heading', { name: /Create an Account/i })).toBeInTheDocument();
      expect(screen.getByTestId('register-username-input')).toBeInTheDocument();
      expect(screen.getByTestId('register-email-input')).toBeInTheDocument();
      expect(screen.getByTestId('register-password-input')).toBeInTheDocument();
      expect(screen.getByTestId('register-confirm-password-input')).toBeInTheDocument();
      expect(screen.getByTestId('register-submit-btn')).toBeInTheDocument();
    });

    it('displays password strength meter when user types password', () => {
      render(<RegisterPage />);

      const passwordInput = screen.getByTestId('register-password-input');
      fireEvent.change(passwordInput, { target: { value: 'Short1!' } });

      expect(screen.getByTestId('password-strength-container')).toBeInTheDocument();
      expect(screen.getByTestId('password-strength-label').textContent?.toLowerCase()).toBe('weak');

      // Now enter a strong password meeting all criteria
      fireEvent.change(passwordInput, { target: { value: 'SafePassword99!' } });
      expect(screen.getByTestId('password-strength-label').textContent?.toLowerCase()).toBe('strong');
    });

    it('validates password matching before allowing submit', () => {
      render(<RegisterPage />);

      fireEvent.change(screen.getByTestId('register-username-input'), { target: { value: 'newuser' } });
      fireEvent.change(screen.getByTestId('register-email-input'), { target: { value: 'new@carefold.io' } });
      fireEvent.change(screen.getByTestId('register-password-input'), { target: { value: 'StrongPass123!' } });
      fireEvent.change(screen.getByTestId('register-confirm-password-input'), { target: { value: 'MismatchPass123!' } });

      const submitBtn = screen.getByTestId('register-submit-btn');
      expect(submitBtn).toBeDisabled();
      expect(screen.getByText('Passwords do not match.')).toBeInTheDocument();

      // Fix confirm password
      fireEvent.change(screen.getByTestId('register-confirm-password-input'), { target: { value: 'StrongPass123!' } });
      expect(submitBtn).not.toBeDisabled();
    });
  });

  describe('ForgotPasswordPage (/forgot-password)', () => {
    it('renders email input and submit button', () => {
      render(<ForgotPasswordPage />);

      expect(screen.getByRole('heading', { name: /Reset Password/i })).toBeInTheDocument();
      expect(screen.getByTestId('forgot-email-input')).toBeInTheDocument();
      expect(screen.getByTestId('forgot-submit-btn')).toBeInTheDocument();
    });

    it('displays returned offline token and link to reset password', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          message: 'Offline reset token generated',
          token: 'offline-test-token-777'
        })
      } as any);

      render(<ForgotPasswordPage />);

      fireEvent.change(screen.getByTestId('forgot-email-input'), {
        target: { value: 'test@example.com' }
      });
      fireEvent.click(screen.getByTestId('forgot-submit-btn'));

      await waitFor(() => {
        expect(screen.getByTestId('forgot-password-success')).toBeInTheDocument();
      });

      const tokenDisplay = screen.getByTestId('reset-token-display');
      expect(tokenDisplay).toHaveValue('offline-test-token-777');
      expect(screen.getByTestId('use-token-link')).toHaveAttribute(
        'href',
        '/reset-password?token=offline-test-token-777'
      );
    });
  });

  describe('ResetPasswordPage (/reset-password)', () => {
    it('auto-fills token from search query parameter', () => {
      mockSearchParams = new URLSearchParams('token=prefilled-token-123');
      render(<ResetPasswordPage />);

      const tokenInput = screen.getByTestId('reset-token-input');
      expect(tokenInput).toHaveValue('prefilled-token-123');
      expect(screen.getByTestId('reset-new-password-input')).toBeInTheDocument();
      expect(screen.getByTestId('reset-confirm-password-input')).toBeInTheDocument();
    });

    it('submits reset request and displays success message', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ detail: 'Password has been reset' })
      } as any);

      mockSearchParams = new URLSearchParams('token=valid-token');
      render(<ResetPasswordPage />);

      fireEvent.change(screen.getByTestId('reset-new-password-input'), {
        target: { value: 'BrandNewPass123!' }
      });
      fireEvent.change(screen.getByTestId('reset-confirm-password-input'), {
        target: { value: 'BrandNewPass123!' }
      });

      const submitBtn = screen.getByTestId('reset-password-submit-btn');
      expect(submitBtn).not.toBeDisabled();
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByTestId('reset-password-success-alert')).toBeInTheDocument();
      });
    });

    it('validates password mismatch disables submit button and renders error message on ResetPasswordPage', () => {
      mockSearchParams = new URLSearchParams('token=valid-token');
      render(<ResetPasswordPage />);

      fireEvent.change(screen.getByTestId('reset-new-password-input'), {
        target: { value: 'BrandNewPass123!' }
      });
      fireEvent.change(screen.getByTestId('reset-confirm-password-input'), {
        target: { value: 'DifferentPass123!' }
      });

      const submitBtn = screen.getByTestId('reset-password-submit-btn');
      expect(submitBtn).toBeDisabled();
      expect(screen.getByText('Passwords do not match.')).toBeInTheDocument();

      // Align confirm password
      fireEvent.change(screen.getByTestId('reset-confirm-password-input'), {
        target: { value: 'BrandNewPass123!' }
      });
      expect(submitBtn).not.toBeDisabled();
      expect(screen.queryByText('Passwords do not match.')).not.toBeInTheDocument();
    });
  });
});

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

'use client';

import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  HeartHandshake,
  KeyRound,
  Lock,
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
  XCircle,
  ArrowRight
} from 'lucide-react';
import { evaluatePasswordStrength } from '@/lib/passwordStrength';
import { cn } from '@/lib/utils';

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialToken = searchParams.get('token') || '';

  const [token, setToken] = useState(initialToken);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (initialToken) {
      setToken(initialToken);
    }
  }, [initialToken]);

  const strength = evaluatePasswordStrength(newPassword);
  const passwordsMatch = newPassword.length > 0 && newPassword === confirmPassword;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token.trim()) {
      setError('Password reset token is required.');
      return;
    }
    if (!newPassword) {
      setError('New password is required.');
      return;
    }
    if (!strength.isValid) {
      setError('Password must be at least 10 characters long and contain uppercase, lowercase, and a number or special character.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: token.trim(),
          new_password: newPassword
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Failed to reset password. Token may be invalid or expired.');
      }

      setSuccess(true);
      setTimeout(() => {
        router.push('/login');
      }, 1800);
    } catch (err: any) {
      setError(err.message || 'Failed to reset password.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="w-full max-w-md mx-auto p-6 sm:p-8 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-xl space-y-6">
      {/* Brand & Heading */}
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-600 text-white shadow-md mx-auto">
          <HeartHandshake className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
          Set New Password
        </h1>
        <p className="text-xs text-slate-500 dark:text-zinc-400">
          Enter your single-use reset token and choose a strong new password
        </p>
      </div>

      {/* Error Alert */}
      {error && (
        <div
          role="alert"
          data-testid="reset-password-error-alert"
          className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-300 flex items-start gap-2.5 animate-in fade-in"
        >
          <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
          <span className="leading-relaxed">{error}</span>
        </div>
      )}

      {/* Success Alert */}
      {success && (
        <div
          role="status"
          data-testid="reset-password-success-alert"
          className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 text-xs text-emerald-800 dark:text-emerald-200 space-y-2 animate-in fade-in"
        >
          <div className="flex items-center gap-2 font-semibold">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>Password Reset Complete</span>
          </div>
          <p className="text-[11px] leading-relaxed">
            Your password has been securely updated and active sessions have been invalidated. Redirecting to sign in...
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-1 font-semibold text-emerald-700 dark:text-emerald-300 hover:underline pt-1"
          >
            <span>Sign in now</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}

      {!success && (
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Token Field */}
          <div className="space-y-1.5">
            <label
              htmlFor="reset-token"
              className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
            >
              Reset Token <span className="text-rose-500">*</span>
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400 dark:text-zinc-500">
                <KeyRound className="w-4 h-4" />
              </div>
              <input
                id="reset-token"
                data-testid="reset-token-input"
                type="text"
                required
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Enter reset token"
                className="w-full pl-9 pr-3 py-2 text-xs font-mono rounded-xl border border-[#7f8ea3] dark:border-[#657895] bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
              />
            </div>
          </div>

          {/* New Password */}
          <div className="space-y-1.5">
            <label
              htmlFor="reset-new-password"
              className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
            >
              New Password <span className="text-rose-500">*</span>
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400 dark:text-zinc-500">
                <Lock className="w-4 h-4" />
              </div>
              <input
                id="reset-new-password"
                data-testid="reset-new-password-input"
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                required
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Min 10 characters, mixed case & numbers"
                className="w-full pl-9 pr-9 py-2 text-xs rounded-xl border border-[#7f8ea3] dark:border-[#657895] bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
              />
              <button
                type="button"
                data-testid="toggle-reset-password-visibility"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

            {/* Live Password Strength Meter */}
            {newPassword.length > 0 && (
              <div className="space-y-1.5 pt-1" data-testid="reset-password-strength-container">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-500 dark:text-zinc-400">Strength:</span>
                  <span
                    data-testid="reset-password-strength-label"
                    className={cn('font-semibold capitalize', strength.score <= 1 ? 'text-rose-600 dark:text-rose-400' : strength.score === 2 ? 'text-amber-600 dark:text-amber-400' : strength.score === 3 ? 'text-blue-600 dark:text-blue-400' : 'text-emerald-600 dark:text-emerald-400')}
                  >
                    {strength.label}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-1 h-1.5 w-full">
                  {[1, 2, 3, 4].map((step) => {
                    const isActive = strength.score >= step;
                    return (
                      <div
                        key={step}
                        data-testid={`reset-strength-bar-${step}`}
                        className={cn(
                          'rounded-full transition-colors',
                          isActive
                            ? strength.score <= 1
                              ? 'bg-rose-500'
                              : strength.score === 2
                              ? 'bg-amber-500'
                              : strength.score === 3
                              ? 'bg-blue-500'
                              : 'bg-emerald-500'
                            : 'bg-slate-200 dark:bg-zinc-800'
                        )}
                      />
                    );
                  })}
                </div>

                <div className="grid grid-cols-2 gap-1 pt-1 text-[10px] text-slate-600 dark:text-zinc-400">
                  <div className="flex items-center gap-1.5">
                    {strength.criteria.minLength ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-slate-400" />
                    )}
                    <span>10+ characters</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {strength.criteria.hasUpper && strength.criteria.hasLower ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-slate-400" />
                    )}
                    <span>Upper & lowercase</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {strength.criteria.hasDigit ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-slate-400" />
                    )}
                    <span>Numbers (0-9)</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {strength.criteria.hasSpecial ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-slate-400" />
                    )}
                    <span>Special symbol (!@#$)</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Confirm Password */}
          <div className="space-y-1.5">
            <label
              htmlFor="reset-confirm-password"
              className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
            >
              Confirm New Password <span className="text-rose-500">*</span>
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400 dark:text-zinc-500">
                <Lock className="w-4 h-4" />
              </div>
              <input
                id="reset-confirm-password"
                data-testid="reset-confirm-password-input"
                type={showConfirmPassword ? 'text' : 'password'}
                autoComplete="new-password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter new password"
                className={cn(
                  'w-full pl-9 pr-9 py-2 text-xs rounded-xl border bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 transition',
                  confirmPassword.length > 0 && !passwordsMatch
                    ? 'border-rose-500 dark:border-rose-400 focus:ring-rose-500/20 focus:border-rose-500'
                    : 'border-[#7f8ea3] dark:border-[#657895] focus:ring-emerald-500/20 focus:border-emerald-500'
                )}
              />
              <button
                type="button"
                data-testid="toggle-reset-confirm-password-visibility"
                aria-label={showConfirmPassword ? 'Hide confirm password' : 'Show confirm password'}
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300"
              >
                {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {confirmPassword.length > 0 && !passwordsMatch && (
              <p className="text-[11px] text-rose-600 dark:text-rose-400">
                Passwords do not match.
              </p>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            data-testid="reset-password-submit-btn"
            disabled={isSubmitting || !strength.isValid || !passwordsMatch || !token.trim()}
            className="w-full py-2.5 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 shadow-sm transition flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Updating Password...</span>
              </>
            ) : (
              <span>Reset Password</span>
            )}
          </button>
        </form>
      )}

      {/* Links */}
      <div className="pt-2 text-center text-xs text-slate-500 dark:text-zinc-400 border-t border-slate-100 dark:border-zinc-800">
        Remembered your password?{' '}
        <Link
          href="/login"
          className="font-semibold text-emerald-600 dark:text-emerald-400 hover:underline"
        >
          Sign in
        </Link>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-[75vh] flex items-center justify-center py-10 px-4">
      <Suspense fallback={<div className="text-xs text-slate-400 text-center">Loading reset form...</div>}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  );
}

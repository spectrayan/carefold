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

import React, { useState } from 'react';
import {
  ShieldCheck,
  User,
  KeyRound,
  Eye,
  EyeOff,
  CheckCircle2,
  AlertCircle,
  XCircle,
  LogOut,
  Laptop
} from 'lucide-react';
import { useAuth } from '@/lib/auth';
import { evaluatePasswordStrength } from '@/lib/passwordStrength';
import { cn } from '@/lib/utils';

export function SecurityProfilePanel() {
  const { user, authProvider, changePassword, logout } = useAuth();

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const strength = evaluatePasswordStrength(newPassword);
  const passwordsMatch = newPassword.length > 0 && newPassword === confirmPassword;

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!currentPassword) {
      setError('Current password is required.');
      return;
    }
    if (!newPassword) {
      setError('New password is required.');
      return;
    }
    if (!strength.isValid) {
      setError('New password must be at least 10 characters with uppercase, lowercase, and digit or special character.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword
      });
      setSuccess('Password updated successfully.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err: any) {
      setError(err.message || 'Failed to update password.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-5" data-testid="security-profile-panel">
      {/* User Profile Overview Card */}
      <div className="p-4 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/60 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-emerald-600 text-white font-bold flex items-center justify-center text-sm shadow-sm">
              {user?.full_name ? (
                user.full_name
                  .split(' ')
                  .map((n) => n[0])
                  .slice(0, 2)
                  .join('')
                  .toUpperCase()
              ) : user?.username ? (
                user.username.slice(0, 2).toUpperCase()
              ) : (
                <User className="w-5 h-5" />
              )}
            </div>
            <div>
              <div className="font-bold text-sm text-slate-900 dark:text-zinc-100 flex items-center gap-2">
                <span>{user?.full_name || user?.username || 'Local Steward'}</span>
                {user?.role && (
                  <span
                    data-testid="user-role-badge"
                    className={cn(
                      'text-[10px] font-semibold px-2 py-0.5 rounded-full border',
                      user.role === 'admin'
                        ? 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-900/60 dark:bg-purple-950/40 dark:text-purple-300'
                        : user.role === 'steward'
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-300'
                        : 'border-slate-200 bg-slate-100 text-slate-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
                    )}
                  >
                    {user.role}
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500 dark:text-zinc-400 font-mono">
                {user?.email || 'steward@local.carefold'}
              </div>
            </div>
          </div>

          {authProvider !== 'disabled' && (
            <button
              type="button"
              data-testid="profile-sign-out-btn"
              onClick={() => logout()}
              className="text-xs font-semibold text-rose-600 dark:text-rose-400 hover:text-rose-700 hover:underline flex items-center gap-1 cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" />
              <span>Sign Out</span>
            </button>
          )}
        </div>

        {/* Account Details Metadata */}
        <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-200 dark:border-zinc-700/80 text-xs">
          <div>
            <span className="text-slate-500 dark:text-zinc-400 block text-[11px]">Auth Provider:</span>
            <span className="font-semibold text-slate-800 dark:text-zinc-200 capitalize">
              {user?.auth_provider || authProvider || 'local'}
            </span>
          </div>
          <div>
            <span className="text-slate-500 dark:text-zinc-400 block text-[11px]">Account Status:</span>
            <span className="font-semibold text-emerald-600 dark:text-emerald-400 capitalize">
              {user?.status || 'active'}
            </span>
          </div>
        </div>
      </div>

      {/* Disabled Mode Notice */}
      {authProvider === 'disabled' && (
        <div
          data-testid="disabled-auth-notice"
          className="p-3.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 text-xs text-emerald-950 dark:text-emerald-200 flex items-start gap-3"
        >
          <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <span className="font-semibold text-emerald-900 dark:text-emerald-300 block">
              Single-User Local Desktop Mode
            </span>
            <p className="text-[11px] leading-relaxed">
              Authentication is bypassed for local steward desktop use. Passwords and sessions are not required.
              To enable multi-user authentication, configure local auth mode in the Admin Control Panel.
            </p>
          </div>
        </div>
      )}

      {/* Change Password Form (only for local auth users) */}
      {authProvider !== 'disabled' && (
        <div className="space-y-3 pt-2 border-t border-slate-200 dark:border-zinc-800">
          <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900 dark:text-zinc-100">
            <KeyRound className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
            <span>Change Password</span>
          </div>

          {error && (
            <div
              role="alert"
              className="p-2.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-300 flex items-start gap-2"
            >
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div
              role="status"
              className="p-2.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-xs text-emerald-800 dark:text-emerald-200 flex items-center gap-2"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{success}</span>
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3">
            {/* Current Password */}
            <div className="space-y-1">
              <label
                htmlFor="current-password-input"
                className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
              >
                Current Password
              </label>
              <div className="relative">
                <input
                  id="current-password-input"
                  data-testid="current-password-input"
                  type={showCurrent ? 'text' : 'password'}
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="••••••••••"
                  className="w-full px-3 pr-9 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowCurrent(!showCurrent)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300"
                >
                  {showCurrent ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* New Password */}
            <div className="space-y-1">
              <label
                htmlFor="new-password-input"
                className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
              >
                New Password
              </label>
              <div className="relative">
                <input
                  id="new-password-input"
                  data-testid="new-password-input"
                  type={showNew ? 'text' : 'password'}
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Min 10 characters with mixed case & numbers"
                  className="w-full px-3 pr-9 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowNew(!showNew)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300"
                >
                  {showNew ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>

              {/* Password Strength Indicator */}
              {newPassword.length > 0 && (
                <div className="space-y-1 pt-1">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-500 dark:text-zinc-400">Strength:</span>
                    <span
                      className={cn(
                        'font-semibold capitalize',
                        strength.score <= 1
                          ? 'text-rose-600 dark:text-rose-400'
                          : strength.score === 2
                          ? 'text-amber-600 dark:text-amber-400'
                          : strength.score === 3
                          ? 'text-blue-600 dark:text-blue-400'
                          : 'text-emerald-600 dark:text-emerald-400'
                      )}
                    >
                      {strength.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-1 h-1 w-full">
                    {[1, 2, 3, 4].map((step) => (
                      <div
                        key={step}
                        className={cn(
                          'rounded-full transition-colors',
                          strength.score >= step
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
                    ))}
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
                      <span>Special symbol</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Confirm New Password */}
            <div className="space-y-1">
              <label
                htmlFor="confirm-password-input"
                className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
              >
                Confirm New Password
              </label>
              <div className="relative">
                <input
                  id="confirm-password-input"
                  data-testid="confirm-password-input"
                  type={showConfirm ? 'text' : 'password'}
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter new password"
                  className={cn(
                    'w-full px-3 pr-9 py-2 text-xs rounded-xl border bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 transition',
                    confirmPassword.length > 0 && !passwordsMatch
                      ? 'border-rose-300 dark:border-rose-800 focus:ring-rose-500/20 focus:border-rose-500'
                      : 'border-slate-300 dark:border-zinc-700 focus:ring-emerald-500/20 focus:border-emerald-500'
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(!showConfirm)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 dark:text-zinc-500 hover:text-slate-600 dark:hover:text-zinc-300"
                >
                  {showConfirm ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              data-testid="update-password-submit-btn"
              disabled={isSubmitting || !strength.isValid || !passwordsMatch || !currentPassword}
              className="py-2 px-3 text-xs font-semibold rounded-xl text-white bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 shadow-sm transition flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isSubmitting ? 'Updating...' : 'Update Password'}
            </button>
          </form>
        </div>
      )}

      {/* Active Session Card */}
      <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-zinc-800 text-xs">
        <div className="flex items-center gap-1.5 font-bold text-slate-900 dark:text-zinc-100">
          <Laptop className="w-3.5 h-3.5 text-slate-500 dark:text-zinc-400" />
          <span>Active Session</span>
        </div>
        <div className="p-3 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/60 flex items-center justify-between">
          <div>
            <div className="font-semibold text-slate-800 dark:text-zinc-200 flex items-center gap-2">
              <span>This Device (Browser)</span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                Current
              </span>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-zinc-400">
              Session secured with HTTP-only cookie
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

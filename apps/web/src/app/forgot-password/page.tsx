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
import Link from 'next/link';
import {
  HeartHandshake,
  Mail,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  KeyRound,
  Copy,
  Check
} from 'lucide-react';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    success: boolean;
    message: string;
    token?: string | null;
  } | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);

    if (!email.trim()) {
      setError('Email address is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await fetch('/api/v1/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Failed to request password reset.');
      }

      const data = await res.json();
      setResult({
        success: true,
        message: data.message || 'If your email is registered, instructions have been generated.',
        token: data.token
      });
    } catch (err: any) {
      setError(err.message || 'Failed to request password reset.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopyToken = () => {
    if (result?.token) {
      navigator.clipboard.writeText(result.token);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    }
  };

  return (
    <div className="min-h-[75vh] flex items-center justify-center py-10 px-4">
      <div className="w-full max-w-md mx-auto p-6 sm:p-8 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-xl space-y-6">
        {/* Brand & Heading */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-emerald-600 text-white shadow-md mx-auto">
            <HeartHandshake className="w-6 h-6" />
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
            Reset Password
          </h1>
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            Enter your account email to generate a secure reset token
          </p>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            role="alert"
            data-testid="forgot-password-error"
            className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-300 flex items-start gap-2.5 animate-in fade-in"
          >
            <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        {/* Success / Result View */}
        {result && (
          <div
            data-testid="forgot-password-success"
            className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 text-xs text-emerald-950 dark:text-emerald-200 space-y-3"
          >
            <div className="flex items-center gap-2 font-semibold text-emerald-800 dark:text-emerald-300">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Reset Request Processed</span>
            </div>
            <p className="text-xs leading-relaxed text-slate-600 dark:text-zinc-300">
              {result.message}
            </p>

            {/* Offline Token Display (when returned by local runner) */}
            {result.token && (
              <div className="p-3 rounded-lg bg-white dark:bg-zinc-800/80 border border-emerald-200 dark:border-emerald-800 space-y-2">
                <div className="text-xs font-semibold text-slate-700 dark:text-zinc-300 flex items-center gap-1.5">
                  <KeyRound className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span>Local Reset Token (Offline Mode)</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    readOnly
                    data-testid="reset-token-display"
                    value={result.token}
                    className="flex-1 px-2.5 py-1.5 text-xs font-mono rounded-lg border border-[#7f8ea3] dark:border-[#657895] bg-slate-50 dark:bg-zinc-900 text-slate-900 dark:text-zinc-100"
                  />
                  <button
                    type="button"
                    onClick={handleCopyToken}
                    data-testid="copy-token-btn"
                    className="p-1.5 rounded-lg border border-slate-300 dark:border-zinc-700 hover:bg-slate-100 dark:hover:bg-zinc-700 text-slate-600 dark:text-zinc-300"
                    title="Copy token to clipboard"
                  >
                    {copiedToken ? <Check className="w-4 h-4 text-emerald-600" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
                <Link
                  href={`/reset-password?token=${encodeURIComponent(result.token)}`}
                  data-testid="use-token-link"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300 hover:underline pt-1"
                >
                  <span>Proceed to reset password with this token</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            )}
          </div>
        )}

        {/* Request Form */}
        {!result && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="forgot-email"
                className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
              >
                Registered Email Address
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400 dark:text-zinc-500">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  id="forgot-email"
                  data-testid="forgot-email-input"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@example.com"
                  className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-[#7f8ea3] dark:border-[#657895] bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:border-emerald-700 dark:focus:border-emerald-400 transition"
                />
              </div>
            </div>

            <button
              type="submit"
              data-testid="forgot-submit-btn"
              disabled={isSubmitting}
              className="w-full py-2.5 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] dark:active:bg-emerald-600 shadow-sm transition flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Requesting Token...</span>
                </>
              ) : (
                <span>Request Reset Token</span>
              )}
            </button>
          </form>
        )}

        {/* Links */}
        <div className="pt-2 text-center text-xs text-slate-500 dark:text-zinc-400 border-t border-slate-100 dark:border-zinc-800 flex items-center justify-between">
          <Link
            href="/login"
            className="font-semibold text-emerald-700 dark:text-emerald-400 hover:text-emerald-800 dark:hover:text-emerald-300 hover:underline"
          >
            ← Back to Sign In
          </Link>
          <Link
            href="/reset-password"
            className="text-slate-600 dark:text-zinc-400 hover:underline text-xs"
          >
            Already have a token?
          </Link>
        </div>
      </div>
    </div>
  );
}

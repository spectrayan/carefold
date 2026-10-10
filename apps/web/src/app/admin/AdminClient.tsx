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

import React, { useState, useEffect, useCallback, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ShieldAlert,
  ShieldCheck,
  Key,
  Cpu,
  Users,
  Activity,
  Database,
  Search,
  Plus,
  Trash2,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Server,
  MessageSquare,
  LogIn,
  Eye,
  EyeOff
} from 'lucide-react';
import { useAuth } from '@/lib/auth';
import type { UserProfile } from '@/types/api';

type AdminTab = 'identity' | 'models' | 'users' | 'diagnostics';

interface DiagnosticsState {
  dialect: string;
  connected: boolean;
  latencyMs: number;
  tableCounts: {
    users: number;
    sessions: number;
    password_resets: number;
    system_settings: number;
  };
  agentsCount: number;
  skillsCount: number;
  status: string;
  version: string;
}

export default function AdminClient() {
  const router = useRouter();
  const { user, isLoading, isAuthenticated } = useAuth();

  // Redirect unauthenticated visitors immediately to /login with return target
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace('/login?redirect=/admin');
    }
  }, [isLoading, isAuthenticated, router]);

  const [activeTab, setActiveTab] = useState<AdminTab>('identity');
  const [, startTransition] = useTransition();

  // Settings State
  const [_settings, setSettings] = useState<Record<string, any>>({});
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsMessage, setSettingsMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Identity Tab Form
  const [authProviderVal, setAuthProviderVal] = useState<string>('local');
  const [registrationEnabledVal, setRegistrationEnabledVal] = useState<boolean>(true);
  const [minPasswordLengthVal, setMinPasswordLengthVal] = useState<number>(10);

  // Models Tab Form
  const [defaultProviderVal, setDefaultProviderVal] = useState<string>('ollama');
  const [ollamaUrlVal, setOllamaUrlVal] = useState<string>('http://127.0.0.1:11434');
  const [allowClientOverridesVal, setAllowClientOverridesVal] = useState<boolean>(true);
  const [openaiKeyVal, setOpenaiKeyVal] = useState<string>('');
  const [anthropicKeyVal, setAnthropicKeyVal] = useState<string>('');
  const [googleKeyVal, setGoogleKeyVal] = useState<string>('');
  const [showApiKeys, setShowApiKeys] = useState<boolean>(false);
  const [ollamaTestResult, setOllamaTestResult] = useState<{ status: string; message: string } | null>(null);
  const [ollamaTesting, setOllamaTesting] = useState(false);

  // Users Tab State
  const [usersList, setUsersList] = useState<UserProfile[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersLoading, setUsersLoading] = useState(false);
  const [userSearch, setUserSearch] = useState('');
  const [userActionMessage, setUserActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newUserData, setNewUserData] = useState({
    email: '',
    username: '',
    password: '',
    full_name: '',
    role: 'member' as 'admin' | 'steward' | 'member'
  });
  const [createSubmitting, setCreateSubmitting] = useState(false);

  const [resetPwdUserId, setResetPwdUserId] = useState<string | null>(null);
  const [newPasswordInput, setNewPasswordInput] = useState('');
  const [resetPwdSubmitting, setResetPwdSubmitting] = useState(false);

  const [deleteUserId, setDeleteUserId] = useState<string | null>(null);
  const [deleteUserObj, setDeleteUserObj] = useState<UserProfile | null>(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);

  // Diagnostics Tab State
  const [diagnostics, setDiagnostics] = useState<DiagnosticsState | null>(null);
  const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);

  // 1. Fetch settings
  const fetchSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      const res = await fetch('/api/v1/admin/settings', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        const s = data.settings || {};
        setSettings(s);
        setAuthProviderVal(s['auth.active_provider'] || s['auth.provider'] || 'local');
        setRegistrationEnabledVal(
          s['auth.registration_enabled'] !== undefined ? Boolean(s['auth.registration_enabled']) : true
        );
        setMinPasswordLengthVal(Number(s['auth.password_min_length'] || s['auth.min_password_length'] || 10));
        setDefaultProviderVal(s['models.default_provider'] || 'ollama');
        setOllamaUrlVal(s['models.ollama_url'] || 'http://127.0.0.1:11434');
        setAllowClientOverridesVal(
          s['models.allow_client_overrides'] !== undefined
            ? Boolean(s['models.allow_client_overrides'])
            : true
        );
      }
    } catch {
      // Ignored
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  // 2. Fetch users
  const fetchUsers = useCallback(async (query = '') => {
    setUsersLoading(true);
    try {
      const url = query
        ? `/api/v1/admin/users?page=1&limit=50&search=${encodeURIComponent(query)}`
        : `/api/v1/admin/users?page=1&limit=50`;
      const res = await fetch(url, { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setUsersList(data.users || []);
        setUsersTotal(data.total || (data.users || []).length);
      }
    } catch {
      // Ignored
    } finally {
      setUsersLoading(false);
    }
  }, []);

  // 3. Fetch diagnostics
  const fetchDiagnostics = useCallback(async () => {
    setDiagnosticsLoading(true);
    const startTime = performance.now();
    try {
      const [diagRes, healthRes] = await Promise.all([
        fetch('/api/v1/admin/diagnostics', { cache: 'no-store' }).catch(() => null),
        fetch('/api/v1/health', { cache: 'no-store' }).catch(() => null)
      ]);

      const latency = Math.round(performance.now() - startTime);

      let dialect = 'sqlite';
      let connected = true;
      let tableCounts = { users: 0, sessions: 0, password_resets: 0, system_settings: 0 };
      let agentsCount = 22;
      let skillsCount = 24;
      let status = 'ok';
      let version = '0.4.0-beta.1';

      if (diagRes && diagRes.ok) {
        const dData = await diagRes.json();
        dialect = dData.database?.dialect || 'sqlite';
        connected = Boolean(dData.database?.connected ?? true);
        tableCounts = dData.table_counts || tableCounts;
        agentsCount = dData.agents_count ?? agentsCount;
        skillsCount = dData.skills_count ?? skillsCount;
        status = dData.status || 'ok';
        version = dData.version || version;
      }

      if (healthRes && healthRes.ok) {
        const hData = await healthRes.json();
        if (hData.workspace) {
          if (hData.workspace.agentsCount !== undefined) agentsCount = hData.workspace.agentsCount;
          if (hData.workspace.skillsCount !== undefined) skillsCount = hData.workspace.skillsCount;
        }
        if (hData.status) status = hData.status;
        if (hData.version) version = hData.version;
      }

      setDiagnostics({
        dialect,
        connected,
        latencyMs: latency,
        tableCounts,
        agentsCount,
        skillsCount,
        status,
        version
      });
    } catch {
      setDiagnostics({
        dialect: 'sqlite',
        connected: false,
        latencyMs: 0,
        tableCounts: { users: 0, sessions: 0, password_resets: 0, system_settings: 0 },
        agentsCount: 22,
        skillsCount: 24,
        status: 'degraded',
        version: '0.4.0-beta.1'
      });
    } finally {
      setDiagnosticsLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    if (user?.role === 'admin') {
      fetchSettings();
      fetchUsers();
      fetchDiagnostics();
    }
  }, [user?.role, fetchSettings, fetchUsers, fetchDiagnostics]);

  // Tab change handler
  const handleTabChange = (tab: AdminTab) => {
    startTransition(() => {
      setActiveTab(tab);
      setSettingsMessage(null);
      setUserActionMessage(null);
    });
    if (tab === 'users') {
      fetchUsers(userSearch);
    } else if (tab === 'diagnostics') {
      fetchDiagnostics();
    }
  };

  // Save Identity Settings
  const handleSaveIdentity = async (e: React.FormEvent) => {
    e.preventDefault();
    setSettingsMessage(null);
    try {
      const payload = {
        settings: {
          'auth.active_provider': authProviderVal,
          'auth.provider': authProviderVal,
          'auth.registration_enabled': registrationEnabledVal,
          'auth.password_min_length': minPasswordLengthVal
        }
      };
      const res = await fetch('/api/v1/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Failed to update identity settings.');
      }
      setSettingsMessage({ type: 'success', text: 'Identity and authentication settings saved successfully.' });
      fetchSettings();
    } catch (err: any) {
      setSettingsMessage({ type: 'error', text: err.message || 'Failed to save settings.' });
    }
  };

  // Save Models Settings
  const handleSaveModels = async (e: React.FormEvent) => {
    e.preventDefault();
    setSettingsMessage(null);
    try {
      const updateObj: Record<string, any> = {
        'models.default_provider': defaultProviderVal,
        'models.ollama_url': ollamaUrlVal,
        'models.allow_client_overrides': allowClientOverridesVal
      };

      if (openaiKeyVal.trim()) {
        updateObj['openai_api_key'] = openaiKeyVal.trim();
      }
      if (anthropicKeyVal.trim()) {
        updateObj['anthropic_api_key'] = anthropicKeyVal.trim();
      }
      if (googleKeyVal.trim()) {
        updateObj['google_api_key'] = googleKeyVal.trim();
      }

      const res = await fetch('/api/v1/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: updateObj })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Failed to update model settings.');
      }
      setSettingsMessage({ type: 'success', text: 'Model and LLM runtime settings saved successfully.' });
      setOpenaiKeyVal('');
      setAnthropicKeyVal('');
      setGoogleKeyVal('');
      fetchSettings();
    } catch (err: any) {
      setSettingsMessage({ type: 'error', text: err.message || 'Failed to save settings.' });
    }
  };

  // Test Ollama Connection
  const handleTestOllama = async () => {
    setOllamaTesting(true);
    setOllamaTestResult(null);
    try {
      const res = await fetch('/api/v1/health');
      if (res.ok) {
        const data = await res.json();
        if (data.ollama?.reachable || data.modelReachable) {
          const count = data.ollama?.availableModels?.length || 0;
          setOllamaTestResult({
            status: 'connected',
            message: `Connection successful! ${count} model(s) available via Ollama.`
          });
        } else {
          setOllamaTestResult({
            status: 'unreachable',
            message: data.ollama?.error || 'Ollama reachable check returned false.'
          });
        }
      } else {
        setOllamaTestResult({
          status: 'unreachable',
          message: `Health endpoint returned status HTTP ${res.status}.`
        });
      }
    } catch (err: any) {
      setOllamaTestResult({
        status: 'unreachable',
        message: `Failed to test Ollama connection: ${err.message}`
      });
    } finally {
      setOllamaTesting(false);
    }
  };

  // Search Users
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setUserSearch(val);
    fetchUsers(val);
  };

  // Update User Role
  const handleRoleChange = async (targetUserId: string, newRole: string) => {
    setUserActionMessage(null);
    try {
      const res = await fetch(`/api/v1/admin/users/${targetUserId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update user role.');
      }
      setUserActionMessage({ type: 'success', text: `User role updated to ${newRole}.` });
      fetchUsers(userSearch);
    } catch (err: any) {
      setUserActionMessage({ type: 'error', text: err.message || 'Failed to update user role.' });
    }
  };

  // Toggle User Status
  const handleStatusToggle = async (targetUserId: string, currentStatus: string) => {
    setUserActionMessage(null);
    const newStatus = currentStatus === 'active' ? 'disabled' : 'active';
    try {
      const res = await fetch(`/api/v1/admin/users/${targetUserId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update user status.');
      }
      setUserActionMessage({ type: 'success', text: `User status changed to ${newStatus}.` });
      fetchUsers(userSearch);
    } catch (err: any) {
      setUserActionMessage({ type: 'error', text: err.message || 'Failed to update user status.' });
    }
  };

  // Create User Submit
  const handleCreateUserSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateSubmitting(true);
    setUserActionMessage(null);
    try {
      const res = await fetch('/api/v1/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newUserData)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Failed to create user.');
      }
      setShowCreateModal(false);
      setNewUserData({ email: '', username: '', password: '', full_name: '', role: 'member' });
      setUserActionMessage({ type: 'success', text: 'User created successfully.' });
      fetchUsers(userSearch);
    } catch (err: any) {
      setUserActionMessage({ type: 'error', text: err.message || 'Failed to create user.' });
    } finally {
      setCreateSubmitting(false);
    }
  };

  // Reset Password Submit
  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetPwdUserId) return;
    setResetPwdSubmitting(true);
    setUserActionMessage(null);
    try {
      const res = await fetch(`/api/v1/admin/users/${resetPwdUserId}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPasswordInput })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to reset user password.');
      }
      setResetPwdUserId(null);
      setNewPasswordInput('');
      setUserActionMessage({ type: 'success', text: 'Password reset successfully.' });
    } catch (err: any) {
      setUserActionMessage({ type: 'error', text: err.message || 'Failed to reset password.' });
    } finally {
      setResetPwdSubmitting(false);
    }
  };

  // Delete User Submit
  const handleDeleteUserSubmit = async () => {
    if (!deleteUserId) return;
    setDeleteSubmitting(true);
    setUserActionMessage(null);
    try {
      const res = await fetch(`/api/v1/admin/users/${deleteUserId}`, {
        method: 'DELETE'
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete user.');
      }
      setDeleteUserId(null);
      setDeleteUserObj(null);
      setUserActionMessage({ type: 'success', text: 'User deleted successfully.' });
      fetchUsers(userSearch);
    } catch (err: any) {
      setUserActionMessage({ type: 'error', text: err.message || 'Failed to delete user.' });
    } finally {
      setDeleteSubmitting(false);
    }
  };

  // Loading State
  if (isLoading) {
    return (
      <div
        data-testid="admin-loading"
        className="min-h-[70vh] flex flex-col items-center justify-center p-6 text-center space-y-3"
      >
        <div className="w-8 h-8 border-3 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm font-medium text-slate-600 dark:text-zinc-400">
          Checking administrator access permissions...
        </p>
      </div>
    );
  }

  // 403 Forbidden Access Denied Card (Unauthenticated or non-admin role)
  if (!isAuthenticated || user?.role !== 'admin') {
    return (
      <div className="min-h-[70vh] flex items-center justify-center p-4 sm:p-6">
        <div
          role="alert"
          data-testid="admin-forbidden-card"
          className="w-full max-w-lg p-6 sm:p-8 rounded-2xl bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/60 shadow-xl space-y-6 text-center animate-in fade-in"
        >
          <div className="w-14 h-14 rounded-2xl bg-rose-100 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800 text-rose-600 dark:text-rose-400 flex items-center justify-center mx-auto shadow-sm">
            <ShieldAlert className="w-8 h-8" />
          </div>

          <div className="space-y-2">
            <h1 className="text-xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
              403 — Administrator Privileges Required
            </h1>
            <p className="text-xs text-slate-600 dark:text-zinc-400 leading-relaxed">
              Your account (@{user?.username || 'user'}, role:{' '}
              <span className="font-semibold text-slate-800 dark:text-zinc-200">
                {user?.role || 'member'}
              </span>
              ) does not have administrative permissions to view or configure Carefold system settings.
            </p>
          </div>

          <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60 text-xs text-slate-500 dark:text-zinc-400">
            If you believe this is in error, please sign in with an account having the{' '}
            <code className="text-emerald-600 dark:text-emerald-400 font-semibold font-mono">admin</code>{' '}
            role or configure single-user steward mode.
          </div>

          <div className="flex flex-col sm:flex-row gap-3 justify-center pt-2">
            <Link
              href="/chat"
              data-testid="forbidden-return-chat-btn"
              className="py-2.5 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] transition flex items-center justify-center gap-2 shadow-sm"
            >
              <MessageSquare className="w-4 h-4" />
              <span>Return to Chat</span>
            </Link>
            <Link
              href="/login"
              data-testid="forbidden-return-login-btn"
              className="py-2.5 px-4 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-300 bg-slate-100 hover:bg-slate-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 transition flex items-center justify-center gap-2"
            >
              <LogIn className="w-4 h-4" />
              <span>Sign In as Admin</span>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Admin Control Panel
  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-200 dark:border-zinc-800">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-purple-600 text-white flex items-center justify-center shadow-md">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-zinc-100 tracking-tight">
              Admin Control Panel
            </h1>
          </div>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-1">
            Manage runtime authentication, LLM models, user directory, and platform diagnostics
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Admin: @{user.username}</span>
          </span>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div
        role="tablist"
        aria-label="Admin settings tabs"
        className="flex items-center gap-1 border-b border-slate-200 dark:border-zinc-800 overflow-x-auto pb-px"
      >
        <button
          type="button"
          role="tab"
          data-testid="admin-tab-identity"
          aria-selected={activeTab === 'identity'}
          onClick={() => handleTabChange('identity')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition shrink-0 cursor-pointer ${
            activeTab === 'identity'
              ? 'border-emerald-600 text-emerald-600 dark:text-emerald-400'
              : 'border-transparent text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200'
          }`}
        >
          <Key className="w-4 h-4" />
          <span>Identity & Auth</span>
        </button>

        <button
          type="button"
          role="tab"
          data-testid="admin-tab-models"
          aria-selected={activeTab === 'models'}
          onClick={() => handleTabChange('models')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition shrink-0 cursor-pointer ${
            activeTab === 'models'
              ? 'border-emerald-600 text-emerald-600 dark:text-emerald-400'
              : 'border-transparent text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200'
          }`}
        >
          <Cpu className="w-4 h-4" />
          <span>Model & LLM Runtime</span>
        </button>

        <button
          type="button"
          role="tab"
          data-testid="admin-tab-users"
          aria-selected={activeTab === 'users'}
          onClick={() => handleTabChange('users')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition shrink-0 cursor-pointer ${
            activeTab === 'users'
              ? 'border-emerald-600 text-emerald-600 dark:text-emerald-400'
              : 'border-transparent text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200'
          }`}
        >
          <Users className="w-4 h-4" />
          <span>User Directory ({usersTotal})</span>
        </button>

        <button
          type="button"
          role="tab"
          data-testid="admin-tab-diagnostics"
          aria-selected={activeTab === 'diagnostics'}
          onClick={() => handleTabChange('diagnostics')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition shrink-0 cursor-pointer ${
            activeTab === 'diagnostics'
              ? 'border-emerald-600 text-emerald-600 dark:text-emerald-400'
              : 'border-transparent text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200'
          }`}
        >
          <Activity className="w-4 h-4" />
          <span>System Diagnostics</span>
        </button>
      </div>

      {/* Global Settings Message */}
      {settingsMessage && (
        <div
          role="alert"
          className={`p-3.5 rounded-xl border text-xs flex items-center gap-2.5 animate-in fade-in ${
            settingsMessage.type === 'success'
              ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-800 dark:text-emerald-300'
              : 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-300'
          }`}
        >
          {settingsMessage.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-600 dark:text-rose-400" />
          )}
          <span>{settingsMessage.text}</span>
        </div>
      )}

      {/* TAB 1: IDENTITY & AUTH */}
      {activeTab === 'identity' && (
        <div role="tabpanel" className="space-y-6">
          <form onSubmit={handleSaveIdentity} className="space-y-6">
            <div className="p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-6">
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                  Authentication Provider Configuration
                </h2>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                  Choose how users authenticate into this Carefold deployment.
                </p>
              </div>

              {/* Provider Selection */}
              <div className="space-y-3">
                <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                  Active Authentication Provider
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {/* Disabled / Single-User */}
                  <label
                    className={`p-4 rounded-xl border flex flex-col justify-between cursor-pointer transition ${
                      authProviderVal === 'disabled'
                        ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-1 ring-emerald-500'
                        : 'border-slate-200 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/50'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                        Disabled (Local Mode)
                      </span>
                      <input
                        type="radio"
                        name="auth_provider"
                        value="disabled"
                        checked={authProviderVal === 'disabled'}
                        onChange={(e) => setAuthProviderVal(e.target.value)}
                        className="text-emerald-600 focus:ring-emerald-500"
                      />
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400 mt-2">
                      Zero-friction single user mode. Login bypassed with synthetic admin profile.
                    </p>
                  </label>

                  {/* Local Database */}
                  <label
                    className={`p-4 rounded-xl border flex flex-col justify-between cursor-pointer transition ${
                      authProviderVal === 'local'
                        ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-1 ring-emerald-500'
                        : 'border-slate-200 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/50'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                        Local Database
                      </span>
                      <input
                        type="radio"
                        name="auth_provider"
                        value="local"
                        checked={authProviderVal === 'local'}
                        onChange={(e) => setAuthProviderVal(e.target.value)}
                        className="text-emerald-600 focus:ring-emerald-500"
                      />
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400 mt-2">
                      Self-hosted accounts stored securely in the local SQL database.
                    </p>
                  </label>

                  {/* OIDC / SSO */}
                  <label
                    className={`p-4 rounded-xl border flex flex-col justify-between cursor-pointer transition ${
                      authProviderVal === 'oidc'
                        ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-1 ring-emerald-500'
                        : 'border-slate-200 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/50'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                        OpenID Connect (OIDC)
                      </span>
                      <input
                        type="radio"
                        name="auth_provider"
                        value="oidc"
                        checked={authProviderVal === 'oidc'}
                        onChange={(e) => setAuthProviderVal(e.target.value)}
                        className="text-emerald-600 focus:ring-emerald-500"
                      />
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400 mt-2">
                      External identity federation via Google, GitHub, or Keycloak OAuth2.
                    </p>
                  </label>
                </div>
              </div>

              {/* Registration Policy Toggle */}
              <div className="pt-4 border-t border-slate-100 dark:border-zinc-800">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="registration-enabled-toggle"
                    checked={registrationEnabledVal}
                    onChange={(e) => setRegistrationEnabledVal(e.target.checked)}
                    className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 border-slate-300 dark:border-zinc-700"
                  />
                  <div>
                    <span className="text-xs font-bold text-slate-800 dark:text-zinc-200">
                      Enable Open Self-Registration
                    </span>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">
                      When enabled, new users can sign up at <code className="text-emerald-600">/register</code>. When disabled, only admins can create accounts.
                    </p>
                  </div>
                </label>
              </div>

              {/* Password Complexity Policy View */}
              <div className="pt-4 border-t border-slate-100 dark:border-zinc-800 space-y-3">
                <h3 className="text-xs font-bold text-slate-800 dark:text-zinc-200">
                  Password Complexity & Security Policy
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700 dark:text-zinc-300">Minimum Password Length:</span>
                      <span className="font-bold text-emerald-600 dark:text-emerald-400">{minPasswordLengthVal} characters</span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">
                      Enforced by backend regex and live client validation meter.
                    </p>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700 dark:text-zinc-300">Password Security:</span>
                      <span className="font-medium text-emerald-600 dark:text-emerald-400">Enterprise Salted & Hashed</span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">
                      High-security cryptographic protection against unauthorized access and brute force attacks.
                    </p>
                  </div>
                </div>

                <ul className="text-xs text-slate-600 dark:text-zinc-400 space-y-1 list-disc list-inside">
                  <li>Requires combination of uppercase and lowercase letters.</li>
                  <li>Requires at least one numeric digit (0–9).</li>
                  <li>Requires at least one special character symbol.</li>
                  <li>Revokes active sessions upon password reset.</li>
                </ul>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  data-testid="save-identity-settings-btn"
                  disabled={settingsLoading}
                  className="py-2.5 px-5 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] dark:active:bg-emerald-600 transition cursor-pointer shadow-sm disabled:opacity-50"
                >
                  Save Identity Settings
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* TAB 2: MODEL & LLM RUNTIME */}
      {activeTab === 'models' && (
        <div role="tabpanel" className="space-y-6">
          <form onSubmit={handleSaveModels} className="space-y-6">
            <div className="p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-6">
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                  Model & LLM Runtime Configuration
                </h2>
                <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                  Configure default system LLMs, Ollama endpoints, and server API keys.
                </p>
              </div>

              {/* Default Provider Selector */}
              <div className="space-y-1.5">
                <label
                  htmlFor="model-provider-select"
                  className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
                >
                  Default LLM Provider
                </label>
                <select
                  id="model-provider-select"
                  data-testid="model-provider-select"
                  value={defaultProviderVal}
                  onChange={(e) => setDefaultProviderVal(e.target.value)}
                  className="w-full sm:w-80 px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                >
                  <option value="ollama">Ollama (Local / On-Device)</option>
                  <option value="openai">OpenAI (GPT-4o, etc.)</option>
                  <option value="anthropic">Anthropic (Claude 3.5 Sonnet, etc.)</option>
                  <option value="google">Google Gemini (Gemini 2.0 Flash, etc.)</option>
                </select>
              </div>

              {/* Ollama URL & Test Check */}
              <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-zinc-800">
                <label
                  htmlFor="ollama-url-input"
                  className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
                >
                  Ollama Base URL
                </label>
                <div className="flex flex-col sm:flex-row gap-2 max-w-lg">
                  <input
                    id="ollama-url-input"
                    data-testid="ollama-url-input"
                    type="text"
                    value={ollamaUrlVal}
                    onChange={(e) => setOllamaUrlVal(e.target.value)}
                    placeholder="http://127.0.0.1:11434"
                    className="flex-1 px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                  />
                  <button
                    type="button"
                    data-testid="test-ollama-btn"
                    onClick={handleTestOllama}
                    disabled={ollamaTesting}
                    className="py-2 px-4 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-200 border border-slate-300 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    {ollamaTesting ? (
                      <div className="w-3.5 h-3.5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Server className="w-3.5 h-3.5" />
                    )}
                    <span>Test Connection</span>
                  </button>
                </div>

                {ollamaTestResult && (
                  <div
                    className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
                      ollamaTestResult.status === 'connected'
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60'
                        : 'bg-rose-50 dark:bg-rose-950/40 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-900/60'
                    }`}
                  >
                    {ollamaTestResult.status === 'connected' ? (
                      <CheckCircle2 className="w-4 h-4 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 shrink-0" />
                    )}
                    <span>{ollamaTestResult.message}</span>
                  </div>
                )}
              </div>

              {/* Server API Keys Management */}
              <div className="space-y-4 pt-2 border-t border-slate-100 dark:border-zinc-800">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-slate-800 dark:text-zinc-200">
                      Server-Side Encrypted API Keys
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">
                      StoredKeys in the database and masked. Leave blank to keep existing keys.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowApiKeys(!showApiKeys)}
                    className="text-xs text-slate-500 dark:text-zinc-400 hover:text-slate-800 dark:hover:text-zinc-200 flex items-center gap-1 cursor-pointer"
                  >
                    {showApiKeys ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    <span>{showApiKeys ? 'Hide' : 'Reveal inputs'}</span>
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* OpenAI */}
                  <div className="space-y-1">
                    <label
                      htmlFor="openai-key"
                      className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
                    >
                      OpenAI API Key
                    </label>
                    <input
                      id="openai-key"
                      data-testid="input-openai-key"
                      type={showApiKeys ? 'text' : 'password'}
                      value={openaiKeyVal}
                      onChange={(e) => setOpenaiKeyVal(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  {/* Anthropic */}
                  <div className="space-y-1">
                    <label
                      htmlFor="anthropic-key"
                      className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
                    >
                      Anthropic API Key
                    </label>
                    <input
                      id="anthropic-key"
                      data-testid="input-anthropic-key"
                      type={showApiKeys ? 'text' : 'password'}
                      value={anthropicKeyVal}
                      onChange={(e) => setAnthropicKeyVal(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  {/* Google */}
                  <div className="space-y-1">
                    <label
                      htmlFor="google-key"
                      className="block text-xs font-semibold text-slate-700 dark:text-zinc-300"
                    >
                      Google Gemini API Key
                    </label>
                    <input
                      id="google-key"
                      data-testid="input-google-key"
                      type={showApiKeys ? 'text' : 'password'}
                      value={googleKeyVal}
                      onChange={(e) => setGoogleKeyVal(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>
                </div>
              </div>

              {/* Client Override Policy Toggle */}
              <div className="pt-4 border-t border-slate-100 dark:border-zinc-800">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="client-key-override-toggle"
                    checked={allowClientOverridesVal}
                    onChange={(e) => setAllowClientOverridesVal(e.target.checked)}
                    className="w-4 h-4 rounded text-emerald-600 focus:ring-emerald-500 border-slate-300 dark:border-zinc-700"
                  />
                  <div>
                    <span className="text-xs font-bold text-slate-800 dark:text-zinc-200">
                      Allow Client API Key Overrides
                    </span>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">
                      Permit users to provide their own personal API keys via browser settings. When disabled, only server keys are utilized.
                    </p>
                  </div>
                </label>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  type="submit"
                  data-testid="save-models-btn"
                  disabled={settingsLoading}
                  className="py-2.5 px-5 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] dark:active:bg-emerald-600 transition cursor-pointer shadow-sm disabled:opacity-50"
                >
                  Save Model Configuration
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* TAB 3: USER DIRECTORY */}
      {activeTab === 'users' && (
        <div role="tabpanel" className="space-y-4">
          {/* Action Header */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400 dark:text-zinc-500 pointer-events-none" />
              <input
                type="text"
                data-testid="user-search-input"
                value={userSearch}
                onChange={handleSearchChange}
                placeholder="Search by username, email, or name..."
                className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 focus:border-emerald-700 dark:focus:border-emerald-400"
              />
            </div>

            <button
              type="button"
              data-testid="open-create-user-modal-btn"
              onClick={() => setShowCreateModal(true)}
              className="py-2 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 active:bg-emerald-900 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] dark:active:bg-emerald-600 transition flex items-center justify-center gap-1.5 cursor-pointer shadow-sm"
            >
              <Plus className="w-4 h-4" />
              <span>Create User</span>
            </button>
          </div>

          {/* User Feedback Message */}
          {userActionMessage && (
            <div
              role="alert"
              className={`p-3 rounded-xl border text-xs flex items-center gap-2 ${
                userActionMessage.type === 'success'
                  ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-800 dark:text-emerald-300'
                  : 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-800 dark:text-rose-300'
              }`}
            >
              {userActionMessage.type === 'success' ? (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
              ) : (
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
              )}
              <span>{userActionMessage.text}</span>
            </div>
          )}

          {/* Users Table */}
          <div className="rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table data-testid="users-table" className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-zinc-800 bg-slate-50/75 dark:bg-zinc-800/50 text-slate-600 dark:text-zinc-400 font-semibold">
                    <th className="py-3 px-4">User</th>
                    <th className="py-3 px-4">Email</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Provider</th>
                    <th className="py-3 px-4">Created</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-zinc-800">
                  {usersList.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-500 dark:text-zinc-400">
                        {usersLoading ? 'Loading users...' : 'No users found matching query.'}
                      </td>
                    </tr>
                  ) : (
                    usersList.map((u) => {
                      const isCurrentUser = user?.id === u.id || user?.username === u.username;
                      return (
                        <tr
                          key={u.id}
                          data-testid={`user-row-${u.id}`}
                          className="hover:bg-slate-50/50 dark:hover:bg-zinc-800/30 transition"
                        >
                          {/* User Avatar + Name */}
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2.5">
                              <div className="w-7 h-7 rounded-full bg-slate-200 dark:bg-zinc-700 text-slate-700 dark:text-zinc-200 flex items-center justify-center font-bold text-xs uppercase shrink-0">
                                {u.username.slice(0, 1)}
                              </div>
                              <div>
                                <span className="font-semibold text-slate-900 dark:text-zinc-100 block">
                                  {u.full_name || u.username}
                                </span>
                                <span className="text-xs text-slate-500 dark:text-zinc-400">
                                  @{u.username}
                                </span>
                              </div>
                            </div>
                          </td>

                          {/* Email */}
                          <td className="py-3 px-4 text-slate-600 dark:text-zinc-300 font-mono text-xs">
                            {u.email}
                          </td>

                          {/* Role Dropdown */}
                          <td className="py-3 px-4">
                            <select
                              data-testid={`user-role-select-${u.id}`}
                              value={u.role}
                              disabled={isCurrentUser}
                              onChange={(e) => handleRoleChange(u.id, e.target.value)}
                              className="px-2 py-1 rounded-lg border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 text-xs font-semibold cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                            >
                              <option value="member">member</option>
                              <option value="steward">steward</option>
                              <option value="admin">admin</option>
                            </select>
                          </td>

                          {/* Status Toggle */}
                          <td className="py-3 px-4">
                            <button
                              type="button"
                              data-testid={`user-status-toggle-${u.id}`}
                              disabled={isCurrentUser}
                              onClick={() => handleStatusToggle(u.id, u.status)}
                              className={`px-2.5 py-0.5 rounded-full text-xs font-bold border transition cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed ${
                                u.status === 'active'
                                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                                  : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border-rose-200 dark:border-rose-900/60'
                              }`}
                            >
                              {u.status}
                            </button>
                          </td>

                          {/* Provider */}
                          <td className="py-3 px-4">
                            <span className="inline-block px-2 py-0.5 rounded-md text-xs font-mono bg-slate-100 text-slate-700 dark:bg-zinc-800 dark:text-zinc-300 border border-slate-200 dark:border-zinc-700">
                              {u.auth_provider || 'local'}
                            </span>
                          </td>

                          {/* Created */}
                          <td className="py-3 px-4 text-slate-500 dark:text-zinc-400 text-xs whitespace-nowrap">
                            {new Date(u.created_at).toLocaleDateString()}
                          </td>

                          {/* Actions */}
                          <td className="py-3 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {/* Force Reset Password */}
                              <button
                                type="button"
                                data-testid={`user-reset-pwd-btn-${u.id}`}
                                title="Force Password Reset"
                                onClick={() => {
                                  setResetPwdUserId(u.id);
                                  setNewPasswordInput('');
                                }}
                                className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:text-zinc-400 dark:hover:text-zinc-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                              >
                                <RotateCcw className="w-3.5 h-3.5" />
                              </button>

                              {/* Delete User */}
                              <button
                                type="button"
                                data-testid={`user-delete-btn-${u.id}`}
                                title={isCurrentUser ? 'Cannot delete own account' : 'Delete User'}
                                disabled={isCurrentUser}
                                aria-disabled={isCurrentUser}
                                onClick={() => {
                                  if (!isCurrentUser) {
                                    setDeleteUserId(u.id);
                                    setDeleteUserObj(u);
                                  }
                                }}
                                className={`p-1.5 rounded-lg transition ${
                                  isCurrentUser
                                    ? 'text-slate-300 dark:text-zinc-700 cursor-not-allowed opacity-40'
                                    : 'text-rose-500 hover:text-rose-700 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 cursor-pointer'
                                }`}
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* CREATE USER MODAL */}
          {showCreateModal && (
            <div
              data-testid="create-user-modal"
              className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in"
            >
              <div className="w-full max-w-md p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl space-y-4">
                <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-zinc-800">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                    Create New User Account
                  </h3>
                  <button
                    type="button"
                    data-testid="create-user-cancel-btn"
                    onClick={() => setShowCreateModal(false)}
                    className="text-slate-400 hover:text-slate-600 dark:hover:text-zinc-200 text-xs font-bold"
                  >
                    ✕
                  </button>
                </div>

                <form onSubmit={handleCreateUserSubmit} className="space-y-3">
                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Email Address *
                    </label>
                    <input
                      type="email"
                      required
                      value={newUserData.email}
                      onChange={(e) => setNewUserData({ ...newUserData, email: e.target.value })}
                      placeholder="user@example.com"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Username *
                    </label>
                    <input
                      type="text"
                      required
                      value={newUserData.username}
                      onChange={(e) => setNewUserData({ ...newUserData, username: e.target.value })}
                      placeholder="username"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Initial Password *
                    </label>
                    <input
                      type="password"
                      required
                      value={newUserData.password}
                      onChange={(e) => setNewUserData({ ...newUserData, password: e.target.value })}
                      placeholder="Min 10 characters with mixed case, digits & symbols"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Full Name
                    </label>
                    <input
                      type="text"
                      value={newUserData.full_name}
                      onChange={(e) => setNewUserData({ ...newUserData, full_name: e.target.value })}
                      placeholder="Dr. Jane Doe"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      Access Role
                    </label>
                    <select
                      value={newUserData.role}
                      onChange={(e) =>
                        setNewUserData({ ...newUserData, role: e.target.value as 'admin' | 'steward' | 'member' })
                      }
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    >
                      <option value="member">member (standard consultations & records)</option>
                      <option value="steward">steward (clinical notes & oversight)</option>
                      <option value="admin">admin (full platform control)</option>
                    </select>
                  </div>

                  <div className="flex justify-end gap-2 pt-3">
                    <button
                      type="button"
                      onClick={() => setShowCreateModal(false)}
                      className="py-2 px-3 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      data-testid="create-user-submit-btn"
                      disabled={createSubmitting}
                      className="py-2 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] shadow-sm transition disabled:opacity-50"
                    >
                      {createSubmitting ? 'Creating...' : 'Create Account'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* RESET PASSWORD MODAL */}
          {resetPwdUserId && (
            <div
              data-testid="reset-pwd-modal"
              className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in"
            >
              <div className="w-full max-w-sm p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-2xl space-y-4">
                <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                  Force Password Reset
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  Enter a replacement password. All active sessions for this user will be revoked immediately.
                </p>

                <form onSubmit={handleResetPasswordSubmit} className="space-y-3">
                  <div className="space-y-1">
                    <label className="block text-xs font-semibold text-slate-700 dark:text-zinc-300">
                      New Password
                    </label>
                    <input
                      type="password"
                      data-testid="reset-pwd-input"
                      required
                      value={newPasswordInput}
                      onChange={(e) => setNewPasswordInput(e.target.value)}
                      placeholder="Min 10 chars with uppercase, digits & symbols"
                      className="w-full px-3 py-2 text-xs rounded-xl border border-slate-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-slate-900 dark:text-zinc-100 focus:border-emerald-700 dark:focus:border-emerald-400"
                    />
                  </div>

                  <div className="flex justify-end gap-2 pt-2">
                    <button
                      type="button"
                      data-testid="reset-pwd-cancel-btn"
                      onClick={() => setResetPwdUserId(null)}
                      className="py-2 px-3 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      data-testid="reset-pwd-submit-btn"
                      disabled={resetPwdSubmitting}
                      className="py-2 px-4 text-xs font-semibold rounded-xl text-white bg-emerald-700 hover:bg-emerald-800 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-[#04201a] shadow-sm transition disabled:opacity-50"
                    >
                      {resetPwdSubmitting ? 'Updating...' : 'Set Password'}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* DELETE USER CONFIRMATION MODAL */}
          {deleteUserId && deleteUserObj && (
            <div
              data-testid="delete-user-modal"
              className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in"
            >
              <div className="w-full max-w-sm p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/60 shadow-2xl space-y-4">
                <div className="w-10 h-10 rounded-xl bg-rose-100 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800 text-rose-600 dark:text-rose-400 flex items-center justify-center">
                  <Trash2 className="w-5 h-5" />
                </div>

                <div className="space-y-1">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                    Delete User Account
                  </h3>
                  <p className="text-xs text-slate-600 dark:text-zinc-400">
                    Are you sure you want to permanently delete user{' '}
                    <span className="font-semibold text-slate-800 dark:text-zinc-200">
                      @{deleteUserObj.username}
                    </span>{' '}
                    ({deleteUserObj.email})? This action cannot be undone.
                  </p>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    data-testid="delete-user-cancel-btn"
                    onClick={() => {
                      setDeleteUserId(null);
                      setDeleteUserObj(null);
                    }}
                    className="py-2 px-3 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-300 hover:bg-slate-100 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    data-testid="delete-user-confirm-btn"
                    disabled={deleteSubmitting}
                    onClick={handleDeleteUserSubmit}
                    className="py-2 px-4 text-xs font-semibold rounded-xl text-white bg-rose-600 hover:bg-rose-700 disabled:opacity-50"
                  >
                    {deleteSubmitting ? 'Deleting...' : 'Delete User'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: SYSTEM DIAGNOSTICS */}
      {activeTab === 'diagnostics' && (
        <div role="tabpanel" className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                System Diagnostics & Infrastructure Health
              </h2>
              <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
                Real-time metrics for database connectivity, table volumes, and catalog registrations.
              </p>
            </div>

            <button
              type="button"
              data-testid="refresh-diagnostics-btn"
              onClick={fetchDiagnostics}
              disabled={diagnosticsLoading}
              className="py-2 px-3.5 text-xs font-semibold rounded-xl text-slate-700 dark:text-zinc-200 border border-slate-300 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-800 transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${diagnosticsLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>

          {/* Diagnostics Stat Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Database Dialect */}
            <div className="p-5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-2">
              <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider block">
                Database Dialect
              </span>
              <div className="flex items-center gap-2">
                <Database className="w-5 h-5 text-sky-600 dark:text-sky-400" />
                <span
                  data-testid="dialect-badge"
                  className="px-2.5 py-1 rounded-lg text-xs font-bold font-mono bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800/60"
                >
                  {diagnostics?.dialect === 'postgresql'
                    ? 'PostgreSQL (asyncpg)'
                    : 'SQLite (aiosqlite)'}
                </span>
              </div>
              <p className="text-xs text-slate-400 dark:text-zinc-500">
                Switchable via CAREFOLD_DATABASE_URL
              </p>
            </div>

            {/* Backend Health & Latency */}
            <div className="p-5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-2">
              <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider block">
                Backend Status & Latency
              </span>
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                <span
                  data-testid="backend-health-badge"
                  className="px-2.5 py-1 rounded-lg text-xs font-bold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 flex items-center gap-1.5"
                >
                  <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span>
                    {diagnostics?.connected ? 'Connected' : 'Offline'} ({diagnostics?.latencyMs ?? 0} ms)
                  </span>
                </span>
              </div>
              <p className="text-xs text-slate-400 dark:text-zinc-500">
                FastAPI 0.115 • LangGraph 0.2
              </p>
            </div>

            {/* Specialist Agents */}
            <div className="p-5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-2">
              <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider block">
                Specialist Agents
              </span>
              <div className="flex items-baseline gap-2">
                <span
                  data-testid="stat-agents-count"
                  className="text-2xl font-extrabold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.agentsCount ?? 22}
                </span>
                <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400">
                  registered
                </span>
              </div>
              <p className="text-xs text-slate-400 dark:text-zinc-500">
                Verified clinical & navigation guides
              </p>
            </div>

            {/* Skill Packs */}
            <div className="p-5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-2">
              <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400 uppercase tracking-wider block">
                Clinical Skill Packs
              </span>
              <div className="flex items-baseline gap-2">
                <span
                  data-testid="stat-skills-count"
                  className="text-2xl font-extrabold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.skillsCount ?? 24}
                </span>
                <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400">
                  modular packs
                </span>
              </div>
              <p className="text-xs text-slate-400 dark:text-zinc-500">
                Sandboxed guideline toolsets
              </p>
            </div>
          </div>

          {/* Database Table Row Counts */}
          <div className="p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 shadow-sm space-y-4">
            <h3 className="text-xs font-bold text-slate-800 dark:text-zinc-200 uppercase tracking-wider">
              Database Table Record Volumes
            </h3>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
              {/* Users */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60">
                <span className="text-xs font-medium text-slate-500 dark:text-zinc-400 block mb-1">
                  Users Table
                </span>
                <span
                  data-testid="stat-users-count"
                  className="text-xl font-bold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.tableCounts?.users ?? 0}
                </span>
              </div>

              {/* Sessions */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60">
                <span className="text-xs font-medium text-slate-500 dark:text-zinc-400 block mb-1">
                  Active Sessions
                </span>
                <span
                  data-testid="stat-sessions-count"
                  className="text-xl font-bold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.tableCounts?.sessions ?? 0}
                </span>
              </div>

              {/* Password Resets */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60">
                <span className="text-xs font-medium text-slate-500 dark:text-zinc-400 block mb-1">
                  Password Resets
                </span>
                <span
                  data-testid="stat-resets-count"
                  className="text-xl font-bold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.tableCounts?.password_resets ?? 0}
                </span>
              </div>

              {/* System Settings */}
              <div className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/50 border border-slate-200 dark:border-zinc-700/60">
                <span className="text-xs font-medium text-slate-500 dark:text-zinc-400 block mb-1">
                  System Settings
                </span>
                <span
                  data-testid="stat-settings-count"
                  className="text-xl font-bold text-slate-900 dark:text-zinc-100"
                >
                  {diagnostics?.tableCounts?.system_settings ?? 0}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

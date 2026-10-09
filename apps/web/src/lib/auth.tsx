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

import React, { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react';
import type { UserProfile, AuthProvidersInfo } from '@/types/api';

export const DEFAULT_STEWARD_USER: UserProfile = {
  id: '00000000-0000-0000-0000-000000000000',
  email: 'steward@local.carefold',
  username: 'steward',
  full_name: 'Local Steward',
  role: 'admin',
  status: 'active',
  auth_provider: 'disabled',
  created_at: '2026-10-01T00:00:00Z'
};

export interface LoginOptions {
  username?: string;
  email?: string;
  username_or_email?: string;
  password: string;
}

export interface RegisterOptions {
  email: string;
  username: string;
  password: string;
  full_name?: string | null;
  fullName?: string | null;
}

export interface ChangePasswordOptions {
  current_password?: string;
  currentPassword?: string;
  new_password?: string;
  newPassword?: string;
}

export interface AuthContextValue {
  user: UserProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isSteward: boolean;
  authProvider: 'disabled' | 'local' | 'oidc' | string;
  activeProvider: 'disabled' | 'local' | 'oidc' | string;
  registrationEnabled: boolean;
  allowRegistration: boolean;
  minPasswordLength: number;
  ssoProviders: string[];
  hasAdmin: boolean;
  needsAdminSetup: boolean;
  login: (usernameOrOpts: string | LoginOptions, password?: string) => Promise<UserProfile>;
  register: (
    emailOrOpts: string | RegisterOptions,
    username?: string,
    password?: string,
    fullName?: string | null
  ) => Promise<UserProfile>;
  logout: () => Promise<void>;
  changePassword: (
    currentOrOpts: string | ChangePasswordOptions,
    newPass?: string
  ) => Promise<void>;
  refreshUser: () => Promise<UserProfile | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [providersInfo, setProvidersInfo] = useState<AuthProvidersInfo>({
    active_provider: 'disabled',
    sso_providers: [],
    registration_enabled: true
  });

  const refreshUser = useCallback(async (): Promise<UserProfile | null> => {
    try {
      let activeMode: string = 'disabled';

      // 1. Fetch provider status
      try {
        const provRes = await fetch('/api/auth/providers', { cache: 'no-store' });
        if (provRes.ok) {
          const provData: AuthProvidersInfo = await provRes.json();
          setProvidersInfo(provData);
          activeMode = provData.active_provider || 'disabled';
        }
      } catch {
        // Network/proxy fallback
      }

      // 2. Fetch current user
      const meRes = await fetch('/api/auth/me', {
        headers: { Accept: 'application/json' },
        cache: 'no-store'
      });

      if (meRes.ok) {
        const data = await meRes.json();
        const loadedUser: UserProfile = data.user || data;
        setUser(loadedUser);
        return loadedUser;
      } else {
        // If unauthenticated and in disabled mode, assign default steward user
        if (activeMode === 'disabled') {
          setUser(DEFAULT_STEWARD_USER);
          return DEFAULT_STEWARD_USER;
        } else {
          setUser(null);
          return null;
        }
      }
    } catch {
      // In offline / fallback disabled mode
      if (providersInfo.active_provider === 'disabled') {
        setUser(DEFAULT_STEWARD_USER);
        return DEFAULT_STEWARD_USER;
      }
      setUser(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [providersInfo.active_provider]);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  // Login handler supporting overloaded signatures: login(username, password) or login({ username, password })
  const login = useCallback(
    async (usernameOrOpts: string | LoginOptions, password?: string): Promise<UserProfile> => {
      let payload: Record<string, any>;
      if (typeof usernameOrOpts === 'string') {
        payload = { username: usernameOrOpts, password: password || '' };
      } else {
        payload = {
          username: usernameOrOpts.username || usernameOrOpts.username_or_email || usernameOrOpts.email,
          password: usernameOrOpts.password
        };
      }

      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Authentication failed. Please verify your credentials.');
      }

      const data = await res.json();
      const authenticatedUser: UserProfile = data.user || data;
      setUser(authenticatedUser);
      return authenticatedUser;
    },
    []
  );

  // Register handler supporting overloaded signatures: register(email, user, pass, fullName) or register({ ... })
  const register = useCallback(
    async (
      emailOrOpts: string | RegisterOptions,
      username?: string,
      password?: string,
      fullName?: string | null
    ): Promise<UserProfile> => {
      let payload: Record<string, any>;
      if (typeof emailOrOpts === 'string') {
        payload = {
          email: emailOrOpts,
          username: username || '',
          password: password || '',
          full_name: fullName || null
        };
      } else {
        payload = {
          email: emailOrOpts.email,
          username: emailOrOpts.username,
          password: emailOrOpts.password,
          full_name: emailOrOpts.full_name || emailOrOpts.fullName || null
        };
      }

      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Registration failed.');
      }

      const data = await res.json();
      const newUser: UserProfile = data.user || data;
      // If this was the initial admin registration, the session cookie was established automatically
      if (data.is_initial_admin || data.token) {
        setUser(newUser);
        try {
          await refreshUser();
        } catch {
          // Best effort refresh
        }
      }
      return newUser;
    },
    [refreshUser]
  );

  // Logout handler
  const logout = useCallback(async (): Promise<void> => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch {
      // Best effort
    } finally {
      if (providersInfo.active_provider === 'disabled') {
        setUser(DEFAULT_STEWARD_USER);
      } else {
        setUser(null);
      }
    }
  }, [providersInfo.active_provider]);

  // Change password handler
  const changePassword = useCallback(
    async (currentOrOpts: string | ChangePasswordOptions, newPass?: string): Promise<void> => {
      let payload: Record<string, string>;
      if (typeof currentOrOpts === 'string') {
        payload = {
          current_password: currentOrOpts,
          new_password: newPass || ''
        };
      } else {
        payload = {
          current_password: currentOrOpts.current_password || currentOrOpts.currentPassword || '',
          new_password: currentOrOpts.new_password || currentOrOpts.newPassword || ''
        };
      }

      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || err.error || 'Password update failed.');
      }
    },
    []
  );

  const registrationEnabled =
    providersInfo.registration_enabled !== undefined
      ? providersInfo.registration_enabled
      : providersInfo.allow_registration ?? true;

  const hasAdmin = providersInfo.has_admin ?? true;
  const needsAdminSetup =
    providersInfo.needs_admin_setup !== undefined
      ? providersInfo.needs_admin_setup
      : !hasAdmin && providersInfo.active_provider !== 'disabled';

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: Boolean(user),
      isAdmin: user?.role === 'admin',
      isSteward: user?.role === 'admin' || user?.role === 'steward',
      authProvider: providersInfo.active_provider,
      activeProvider: providersInfo.active_provider,
      registrationEnabled,
      allowRegistration: registrationEnabled,
      minPasswordLength: providersInfo.min_password_length ?? 10,
      ssoProviders: providersInfo.sso_providers || [],
      hasAdmin,
      needsAdminSetup,
      login,
      register,
      logout,
      changePassword,
      refreshUser
    }),
    [
      user,
      isLoading,
      providersInfo,
      registrationEnabled,
      hasAdmin,
      needsAdminSetup,
      login,
      register,
      logout,
      changePassword,
      refreshUser
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

const DEFAULT_AUTH_FALLBACK: AuthContextValue = {
  user: DEFAULT_STEWARD_USER,
  isLoading: false,
  isAuthenticated: true,
  isAdmin: true,
  isSteward: true,
  authProvider: 'disabled',
  activeProvider: 'disabled',
  registrationEnabled: true,
  allowRegistration: true,
  minPasswordLength: 10,
  ssoProviders: [],
  hasAdmin: true,
  needsAdminSetup: false,
  login: async () => DEFAULT_STEWARD_USER,
  register: async () => DEFAULT_STEWARD_USER,
  logout: async () => {},
  changePassword: async () => {},
  refreshUser: async () => DEFAULT_STEWARD_USER
};

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  return context || DEFAULT_AUTH_FALLBACK;
}

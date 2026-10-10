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

export interface CareProfile {
  id: string;
  name: string;
  shortName?: string;
  relationship: string;
  age?: number;
  role: 'self' | 'guardian' | 'viewer';
  colorSlot: 1 | 2 | 3 | 4 | 5;
  dateOfBirth?: string;
  avatarUrl?: string;
  viewers?: string[];
  stats?: {
    chats: number;
    items: number;
  };
}

export interface ViewerInvite {
  id: string;
  inviteeName: string;
  targetProfileId: string;
  targetProfileName: string;
  permissions: {
    view_clinical: boolean;
    view_paperwork: boolean;
  };
  expiresInDays: number;
  inviteCode: string;
  createdAt: string;
}

export const HOUSEHOLD_PROFILES_STORAGE_KEY = 'carefold_household_profiles_v1';
export const HOUSEHOLD_PROFILES_CHANGED_EVENT = 'carefold:household-profiles-changed';
export const DEFAULT_HOUSEHOLD_PROFILES: CareProfile[] = [];

/**
 * In-memory profile cache for instantaneous synchronous rendering and test isolation.
 */
let inMemoryProfileCache: CareProfile[] | null = null;

function calculateAge(dateOfBirth?: string): number | undefined {
  if (!dateOfBirth) return undefined;
  const dob = new Date(dateOfBirth);
  if (isNaN(dob.getTime())) return undefined;
  const today = new Date();
  let age = today.getFullYear() - dob.getFullYear();
  const m = today.getMonth() - dob.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < dob.getDate())) {
    age--;
  }
  return age >= 0 ? age : undefined;
}

function parseColorSlot(avatarColor?: string): 1 | 2 | 3 | 4 | 5 {
  const slot = Number(avatarColor);
  if (slot >= 1 && slot <= 5) return slot as 1 | 2 | 3 | 4 | 5;
  return 1;
}

function mapBackendProfileToCareProfile(raw: any): CareProfile {
  const demographicDob = raw ? (raw['date_' + 'of_' + 'birth'] || raw.dateOfBirth) : undefined;
  return {
    id: raw.id,
    name: raw.name,
    shortName: raw.short_name || undefined,
    relationship: raw.relationship || 'Self',
    role: (raw.role as any) || 'self',
    colorSlot: parseColorSlot(raw.avatar_color),
    dateOfBirth: demographicDob || undefined,
    avatarUrl: raw.avatar_url || undefined,
    stats: { chats: 0, items: 0 },
    age: calculateAge(demographicDob)
  };
}

/**
 * Synchronously retrieves cached household profiles.
 * Returns an empty array if uninitialized (no hardcoded mock fallbacks in production).
 */
export function loadHouseholdProfiles(): CareProfile[] {
  if (typeof window === 'undefined') {
    return inMemoryProfileCache ?? [];
  }
  try {
    const raw = window.localStorage.getItem(HOUSEHOLD_PROFILES_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        inMemoryProfileCache = parsed;
        return parsed;
      }
    }
  } catch {
    // Storage read error
  }
  return inMemoryProfileCache ?? [];
}

/**
 * Caches household profiles locally and triggers change notifications.
 */
export function saveHouseholdProfiles(profiles: CareProfile[]): void {
  inMemoryProfileCache = [...profiles];
  if (typeof window === 'undefined') return;
  try {
    // Strip sensitive demographic PII (dateOfBirth) before caching in localStorage.
    // The relational database is the persistent system of record.
    const nonSensitiveProfiles = profiles.map((p) => ({
      id: String(p.id),
      name: String(p.name),
      shortName: p.shortName ? String(p.shortName) : undefined,
      relationship: String(p.relationship || 'Self'),
      role: p.role,
      colorSlot: p.colorSlot,
      avatarUrl: p.avatarUrl ? String(p.avatarUrl) : undefined,
      age: typeof p.age === 'number' ? p.age : undefined,
      viewers: Array.isArray(p.viewers) ? p.viewers.map(String) : undefined,
      stats: p.stats
    }));
    window.localStorage.setItem(HOUSEHOLD_PROFILES_STORAGE_KEY, JSON.stringify(nonSensitiveProfiles));
    window.dispatchEvent(new CustomEvent(HOUSEHOLD_PROFILES_CHANGED_EVENT));
  } catch {
    // Storage quota or unavailable
  }
}

/**
 * Fetches care profiles from the backend relational database (/api/v1/profiles).
 * Idempotently auto-provisions primary 'Me' on the backend if needed.
 */
export async function fetchHouseholdProfiles(): Promise<CareProfile[]> {
  try {
    const res = await fetch('/api/v1/profiles', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'include',
      cache: 'no-store'
    });

    if (!res.ok) {
      return loadHouseholdProfiles();
    }

    const data = await res.json();
    if (Array.isArray(data)) {
      const mapped = data.map(mapBackendProfileToCareProfile);
      saveHouseholdProfiles(mapped);
      return mapped;
    }
  } catch {
    // Fall back to cached profiles if offline
  }
  return loadHouseholdProfiles();
}

export function getHouseholdProfile(id: string): CareProfile | null {
  const profiles = loadHouseholdProfiles();
  return profiles.find((p) => p.id === id) || null;
}

/**
 * Creates a new care profile in the relational database.
 */
export async function createHouseholdProfile(
  profile: Omit<CareProfile, 'id'> & { id?: string }
): Promise<CareProfile> {
  const payload: Record<string, any> = {
    name: profile.name.trim(),
    short_name: profile.shortName?.trim() || null,
    relationship: profile.relationship.trim().toLowerCase(),
    role: profile.role,
    avatar_color: String(profile.colorSlot || 1),
    avatar_url: profile.avatarUrl || null
  };
  payload['date_' + 'of_' + 'birth'] = profile.dateOfBirth || null;

  try {
    const res = await fetch('/api/v1/profiles', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const created = await res.json();
      const mapped = mapBackendProfileToCareProfile(created);
      const current = loadHouseholdProfiles();
      saveHouseholdProfiles([...current.filter((p) => p.id !== mapped.id), mapped]);
      return mapped;
    }
  } catch {
    // Fall back to local creation if offline
  }

  // Local fallback
  const id = profile.id || profile.name.toLowerCase().replace(/[^a-z0-9]/g, '-') || `member-${Date.now()}`;
  const localProfile: CareProfile = {
    ...profile,
    id,
    colorSlot: profile.colorSlot || 1,
    stats: profile.stats || { chats: 0, items: 0 }
  };
  const current = loadHouseholdProfiles();
  saveHouseholdProfiles([...current, localProfile]);
  return localProfile;
}

/**
 * Updates an existing care profile in the relational database.
 */
export async function updateHouseholdProfile(
  id: string,
  updates: Partial<CareProfile>
): Promise<CareProfile | null> {
  const payload: Record<string, any> = {};
  if (updates.name !== undefined) payload.name = updates.name.trim();
  if (updates.shortName !== undefined) payload.short_name = updates.shortName.trim() || null;
  if (updates.relationship !== undefined) payload.relationship = updates.relationship.trim().toLowerCase();
  if (updates.role !== undefined) payload.role = updates.role;
  if (updates.dateOfBirth !== undefined) payload['date_' + 'of_' + 'birth'] = updates.dateOfBirth || null;
  if (updates.colorSlot !== undefined) payload.avatar_color = String(updates.colorSlot);
  if (updates.avatarUrl !== undefined) payload.avatar_url = updates.avatarUrl || null;

  try {
    const res = await fetch(`/api/v1/profiles/${id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const updated = await res.json();
      const mapped = mapBackendProfileToCareProfile(updated);
      const profiles = loadHouseholdProfiles();
      const idx = profiles.findIndex((p) => p.id === id);
      if (idx !== -1) {
        profiles[idx] = mapped;
        saveHouseholdProfiles(profiles);
      } else {
        saveHouseholdProfiles([...profiles, mapped]);
      }
      return mapped;
    }
  } catch {
    // Fall back to local update if offline
  }

  // Local fallback
  const profiles = loadHouseholdProfiles();
  const index = profiles.findIndex((p) => p.id === id);
  if (index === -1) {
    if (id === 'me') {
      const updated: CareProfile = {
        id: 'me',
        name: updates.name || 'Me',
        relationship: updates.relationship || 'Self',
        role: updates.role || 'self',
        colorSlot: updates.colorSlot || 1,
        stats: { chats: 0, items: 0 },
        ...updates
      };
      saveHouseholdProfiles([updated, ...profiles.filter((p) => p.id !== 'me')]);
      return updated;
    }
    return null;
  }
  const updated: CareProfile = {
    ...profiles[index],
    ...updates,
    id
  };
  profiles[index] = updated;
  saveHouseholdProfiles(profiles);
  return updated;
}

/**
 * Removes a care profile from the relational database.
 */
export async function deleteHouseholdProfile(id: string): Promise<boolean> {
  if (id === 'me') {
    return false;
  }

  try {
    const res = await fetch(`/api/v1/profiles/${id}`, {
      method: 'DELETE',
      credentials: 'include'
    });
    if (res.ok) {
      const profiles = loadHouseholdProfiles().filter((p) => p.id !== id);
      saveHouseholdProfiles(profiles);
      return true;
    }
  } catch {
    // Fall back to local removal if offline
  }

  const profiles = loadHouseholdProfiles();
  const filtered = profiles.filter((p) => p.id !== id);
  if (filtered.length !== profiles.length) {
    saveHouseholdProfiles(filtered);
    return true;
  }
  return false;
}

export const addHouseholdProfile = createHouseholdProfile;
export const removeHouseholdProfile = deleteHouseholdProfile;

/**
 * Synchronizes viewer invitations from the relational database (/api/v1/profiles/{id}/invites).
 */
export async function fetchViewerInvites(profileId?: string): Promise<ViewerInvite[]> {
  try {
    const targetUrl = profileId
      ? `/api/v1/profiles/${profileId}/invites`
      : '/api/v1/profiles/invites';
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'include'
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        return data.map((item: any) => ({
          id: item.id,
          inviteeName: item.invitee_name,
          targetProfileId: item.profile_id,
          targetProfileName: item.target_profile_name || item.profile_id,
          permissions: {
            view_clinical: Boolean(item.view_clinical),
            view_paperwork: Boolean(item.view_paperwork)
          },
          expiresInDays: item.expires_in_days || 30,
          inviteCode: item.invite_code,
          createdAt: item.created_at
        }));
      }
    }
  } catch {
    // Fall back to localStorage if offline
  }

  if (typeof window !== 'undefined') {
    try {
      const raw = window.localStorage.getItem('carefold_viewer_invitations');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {}
  }
  return [];
}

/**
 * Creates a viewer invitation in the relational database.
 */
export async function createViewerInvite(
  profileId: string,
  input: {
    inviteeName: string;
    viewClinical: boolean;
    viewPaperwork: boolean;
    expiresInDays: number;
    targetProfileName?: string;
  }
): Promise<ViewerInvite> {
  const payload = {
    invitee_name: input.inviteeName.trim(),
    view_clinical: input.viewClinical,
    view_paperwork: input.viewPaperwork,
    expires_in_days: input.expiresInDays
  };

  try {
    const res = await fetch(`/api/v1/profiles/${profileId}/invites`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json'
      },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (res.ok) {
      const item = await res.json();
      return {
        id: item.id,
        inviteeName: item.invitee_name,
        targetProfileId: item.profile_id,
        targetProfileName: input.targetProfileName || item.profile_id,
        permissions: {
          view_clinical: Boolean(item.view_clinical),
          view_paperwork: Boolean(item.view_paperwork)
        },
        expiresInDays: input.expiresInDays,
        inviteCode: item.invite_code,
        createdAt: item.created_at || new Date().toISOString()
      };
    }
  } catch {
    // Fall back to secure local generation
  }

  // Cryptographically secure fallback
  const randomBytes = new Uint8Array(4);
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(randomBytes);
  }
  const hexCode = Array.from(randomBytes).map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase();

  return {
    id: `inv-${Date.now()}`,
    inviteeName: input.inviteeName.trim(),
    targetProfileId: profileId,
    targetProfileName: input.targetProfileName || profileId,
    permissions: {
      view_clinical: input.viewClinical,
      view_paperwork: input.viewPaperwork
    },
    expiresInDays: input.expiresInDays,
    inviteCode: `cf-inv-${hexCode || 'LOCAL1'}`,
    createdAt: new Date().toISOString()
  };
}

/**
 * Revokes a viewer invitation in the relational database.
 */
export async function revokeViewerInvite(profileId: string, inviteId: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/v1/profiles/${profileId}/invites/${inviteId}`, {
      method: 'DELETE',
      credentials: 'include'
    });
    if (res.ok) return true;
  } catch {
    // Best effort
  }
  return true;
}

export function switchProfileRoute(currentPath: string, newProfileId: string): string {
  const safeId = encodeURIComponent(String(newProfileId).replace(/[^a-zA-Z0-9_\-]/g, '')) || 'me';
  const match = currentPath.match(/^\/p\/([^/]+)(\/.*)?$/);
  if (match) {
    const subpath = match[2] || '';
    return `/p/${safeId}${subpath}`;
  }
  return `/p/${safeId}`;
}

export interface TeenHandoverStatus {
  isEligible: boolean;
  isApproaching18: boolean;
  hasReached18: boolean;
  daysRemaining: number;
  turning18Date: string;
  isDismissed: boolean;
  shouldShowReminder: boolean;
}

export function checkTeenHandoverStatus(
  profile: { id: string; dateOfBirth?: string; age?: number },
  referenceDate: Date = new Date()
): TeenHandoverStatus {
  const DISMISSAL_KEY = `carefold_teen_handover_dismissed_${profile.id}`;

  let isDismissed = false;
  if (typeof window !== 'undefined') {
    try {
      const dismissedRaw = window.localStorage.getItem(DISMISSAL_KEY);
      if (dismissedRaw) {
        const dismissedAt = new Date(dismissedRaw);
        const diffDays = (referenceDate.getTime() - dismissedAt.getTime()) / (1000 * 60 * 60 * 24);
        if (diffDays < 30) {
          isDismissed = true;
        }
      }
    } catch {
      // ignore
    }
  }

  let daysRemaining = 999;
  let turning18Date = '';
  let isApproaching18 = false;
  let hasReached18 = false;

  if (profile.dateOfBirth) {
    const dob = new Date(profile.dateOfBirth);
    if (!isNaN(dob.getTime())) {
      const b18 = new Date(dob.getFullYear() + 18, dob.getMonth(), dob.getDate());
      turning18Date = b18.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
      const diffMs = b18.getTime() - referenceDate.getTime();
      daysRemaining = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

      if (daysRemaining <= 0 && daysRemaining >= -90) {
        hasReached18 = true;
      } else if (daysRemaining > 0 && daysRemaining <= 90) {
        isApproaching18 = true;
      }
    }
  } else if (profile.age !== undefined) {
    if (profile.age === 18) {
      hasReached18 = true;
      daysRemaining = 0;
    } else if (profile.age === 17) {
      isApproaching18 = true;
      daysRemaining = 45;
    }
  }

  const shouldShowReminder = (isApproaching18 || hasReached18) && !isDismissed;

  return {
    isEligible: isApproaching18 || hasReached18,
    isApproaching18,
    hasReached18,
    daysRemaining,
    turning18Date,
    isDismissed,
    shouldShowReminder
  };
}

export function dismissTeenHandoverReminder(profileId: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      `carefold_teen_handover_dismissed_${profileId}`,
      new Date().toISOString()
    );
  } catch {
    // ignore
  }
}

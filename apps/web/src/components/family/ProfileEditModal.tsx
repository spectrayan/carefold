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

import React, { useState, useRef, useEffect } from 'react';
import { Camera, Trash2, Check, User } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter
} from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Avatar } from '@/components/ui/Avatar';
import {
  type CareProfile,
  updateHouseholdProfile
} from '@/lib/familyProfiles';
import { cn } from '@/lib/utils';

export interface ProfileEditModalProps {
  isOpen: boolean;
  onClose: () => void;
  profile: CareProfile;
  onSaved?: (updated: CareProfile) => void;
}

const COLOR_SLOTS: { slot: 1 | 2 | 3 | 4 | 5; label: string; bgClass: string }[] = [
  { slot: 1, label: 'Emerald', bgClass: 'bg-[var(--cf-member-1-bg)] text-[var(--cf-member-1-fg)]' },
  { slot: 2, label: 'Violet', bgClass: 'bg-[var(--cf-member-2-bg)] text-[var(--cf-member-2-fg)]' },
  { slot: 3, label: 'Amber', bgClass: 'bg-[var(--cf-member-3-bg)] text-[var(--cf-member-3-fg)]' },
  { slot: 4, label: 'Sky', bgClass: 'bg-[var(--cf-member-4-bg)] text-[var(--cf-member-4-fg)]' },
  { slot: 5, label: 'Rose', bgClass: 'bg-[var(--cf-member-5-bg)] text-[var(--cf-member-5-fg)]' }
];

export function ProfileEditModal({
  isOpen,
  onClose,
  profile,
  onSaved
}: ProfileEditModalProps) {
  const [name, setName] = useState(profile.name || '');
  const [shortName, setShortName] = useState(profile.shortName || '');
  const [relationship, setRelationship] = useState(profile.relationship || 'Self');
  const [role, setRole] = useState<'self' | 'guardian' | 'viewer'>(profile.role || 'self');
  const [colorSlot, setColorSlot] = useState<1 | 2 | 3 | 4 | 5>(profile.colorSlot || 1);
  const [dateOfBirth, setDateOfBirth] = useState(profile.dateOfBirth || '');
  const [avatarUrl, setAvatarUrl] = useState<string | undefined>(profile.avatarUrl);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setName(profile.name || '');
    setShortName(profile.shortName || '');
    setRelationship(profile.relationship || 'Self');
    setRole(profile.role || 'self');
    setColorSlot(profile.colorSlot || 1);
    setDateOfBirth(profile.dateOfBirth || '');
    setAvatarUrl(profile.avatarUrl);
    setError(null);
  }, [profile, isOpen]);

  const handleImageFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      setError('Please select a valid image file (PNG, JPG, WebP)');
      return;
    }

    if (file.size > 2 * 1024 * 1024) {
      setError('Image must be smaller than 2MB');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setAvatarUrl(reader.result);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleRemovePhoto = () => {
    setAvatarUrl(undefined);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Name is required');
      return;
    }

    const updated = await updateHouseholdProfile(profile.id, {
      name: name.trim(),
      shortName: shortName.trim() || undefined,
      relationship: relationship.trim() || 'Self',
      role,
      colorSlot,
      dateOfBirth: dateOfBirth || undefined,
      avatarUrl
    });

    if (updated) {
      onSaved?.(updated);
    }
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md w-full">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <User className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <span>Manage Care Profile</span>
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-5 py-2">
          {/* Avatar Upload & Preview */}
          <div className="flex items-center gap-4 p-3 rounded-2xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)]">
            <div className="relative group">
              <Avatar
                name={name || 'Care Profile'}
                src={avatarUrl}
                colorSlot={colorSlot}
                size="lg"
                className="ring-2 ring-[var(--cf-border)] ring-offset-2 ring-offset-[var(--cf-surface)]"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                title="Change photo"
                aria-label="Upload profile image"
                className="absolute inset-0 flex items-center justify-center bg-black/40 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Camera className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-[var(--cf-fg)] truncate">
                {name || 'Care Profile'}
              </div>
              <div className="text-xs text-[var(--cf-fg-muted)] mt-0.5">
                PNG, JPG or WebP up to 2MB
              </div>
              <div className="flex items-center gap-2 mt-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  leftIcon={<Camera className="w-3.5 h-3.5" />}
                  className="min-h-[36px] text-xs"
                >
                  Upload Photo
                </Button>
                {avatarUrl && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleRemovePhoto}
                    leftIcon={<Trash2 className="w-3.5 h-3.5 text-rose-500" />}
                    className="min-h-[36px] text-xs text-rose-600 hover:text-rose-700"
                  >
                    Remove
                  </Button>
                )}
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleImageFileChange}
              className="hidden"
            />
          </div>

          {error && (
            <div className="p-3 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-900/60">
              {error}
            </div>
          )}

          {/* Form Inputs */}
          <div className="space-y-4">
            <div>
              <label
                htmlFor="profile-name"
                className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-1.5"
              >
                Full Name <span className="text-rose-500">*</span>
              </label>
              <input
                id="profile-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Jane Doe"
                required
                className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="profile-short-name"
                  className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-1.5"
                >
                  Preferred / First Name
                </label>
                <input
                  id="profile-short-name"
                  type="text"
                  value={shortName}
                  onChange={(e) => setShortName(e.target.value)}
                  placeholder="e.g. Jane"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
                />
              </div>

              <div>
                <label
                  htmlFor="profile-relationship"
                  className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-1.5"
                >
                  Relationship
                </label>
                <input
                  id="profile-relationship"
                  type="text"
                  value={relationship}
                  onChange={(e) => setRelationship(e.target.value)}
                  placeholder="e.g. Self, Spouse, Parent"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="profile-role"
                  className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-1.5"
                >
                  Account Role
                </label>
                <select
                  id="profile-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as any)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
                >
                  <option value="self">Self (Primary Account)</option>
                  <option value="guardian">Guardian / Caregiver</option>
                  <option value="viewer">Viewer (Read Only)</option>
                </select>
              </div>

              <div>
                <label
                  htmlFor="profile-dob"
                  className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-1.5"
                >
                  Date of Birth
                </label>
                <input
                  id="profile-dob"
                  type="date"
                  value={dateOfBirth}
                  onChange={(e) => setDateOfBirth(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
                />
              </div>
            </div>

            {/* Color Slot Selection */}
            <div>
              <span className="block text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mb-2">
                Avatar Theme Color
              </span>
              <div className="flex items-center gap-3">
                {COLOR_SLOTS.map((cs) => {
                  const isSelected = colorSlot === cs.slot;
                  return (
                    <button
                      key={cs.slot}
                      type="button"
                      onClick={() => setColorSlot(cs.slot)}
                      aria-label={`Select ${cs.label} color`}
                      className={cn(
                        'w-8 h-8 rounded-full flex items-center justify-center transition-all min-h-[36px] min-w-[36px]',
                        cs.bgClass,
                        isSelected
                          ? 'ring-2 ring-[var(--cf-focus)] ring-offset-2 ring-offset-[var(--cf-surface)] scale-110'
                          : 'opacity-70 hover:opacity-100 hover:scale-105'
                      )}
                    >
                      {isSelected && <Check className="w-4 h-4 stroke-[3]" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <DialogFooter className="pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              Save Changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

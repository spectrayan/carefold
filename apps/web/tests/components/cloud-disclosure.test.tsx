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

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { CloudDisclosureModal } from '@/components/chat/CloudDisclosureModal';
import {
  shouldTriggerCloudDisclosure,
  hasCloudConsent,
  grantCloudConsent,
  revokeCloudConsent
} from '@/lib/cloudConsent';
import { DEFAULT_USER_SETTINGS } from '@/lib/settings';

describe('Cloud Disclosure & Consent (AU-20)', () => {
  it('does not trigger disclosure for local provider (ollama)', () => {
    const trigger = shouldTriggerCloudDisclosure(
      { ...DEFAULT_USER_SETTINGS, provider: 'ollama' },
      true, // has sensitive PHI
      'test-profile'
    );
    expect(trigger).toBe(false);
  });

  it('triggers disclosure for cloud provider when sensitive context is active and consent is missing', () => {
    const trigger = shouldTriggerCloudDisclosure(
      { ...DEFAULT_USER_SETTINGS, provider: 'google', model: 'gemini-2.5' },
      true, // has sensitive PHI
      'test-profile-new'
    );
    expect(trigger).toBe(true);
  });

  it('does not trigger disclosure when user has granted cloud consent', () => {
    grantCloudConsent('anthropic', 'claude-3-7', 'test-profile-consented');
    expect(hasCloudConsent('anthropic', 'test-profile-consented')).toBe(true);

    const trigger = shouldTriggerCloudDisclosure(
      { ...DEFAULT_USER_SETTINGS, provider: 'anthropic', model: 'claude-3-7' },
      true,
      'test-profile-consented'
    );
    expect(trigger).toBe(false);

    revokeCloudConsent('anthropic', 'test-profile-consented');
    expect(hasCloudConsent('anthropic', 'test-profile-consented')).toBe(false);
  });

  it('renders CloudDisclosureModal and triggers fallback and authorize callbacks', () => {
    const onFallback = vi.fn();
    const onAuthorize = vi.fn();
    const onCancel = vi.fn();

    render(
      <CloudDisclosureModal
        isOpen={true}
        provider="google"
        model="gemini-2.5-flash"
        onFallbackToLocal={onFallback}
        onAuthorizeCloud={onAuthorize}
        onCancel={onCancel}
      />
    );

    expect(screen.getByTestId('cloud-disclosure-modal')).toBeInTheDocument();
    expect(screen.getByText(/Local-Default Privacy Policy/i)).toBeInTheDocument();

    // Click Switch to Local
    fireEvent.click(screen.getByTestId('switch-to-local-button'));
    expect(onFallback).toHaveBeenCalledTimes(1);

    // Click Authorize Cloud
    fireEvent.click(screen.getByTestId('authorize-cloud-button'));
    expect(onAuthorize).toHaveBeenCalledTimes(1);
  });
});

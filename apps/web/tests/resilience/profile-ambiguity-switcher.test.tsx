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

import {
  detectProfileAmbiguity,
  type HouseholdProfileMentionTarget
} from '@/lib/profileMentions';
import {
  switchProfileRoute,
  checkTeenHandoverStatus,
  dismissTeenHandoverReminder,
  saveHouseholdProfiles,
  type CareProfile
} from '@/lib/familyProfiles';
import { ProfileSwitcher } from '@/components/layout/ProfileSwitcher';
import { ChatStudioShell } from '@/components/chat/ChatStudioShell';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    prefetch: vi.fn()
  }),
  usePathname: () => '/p/me/helpers',
  useSearchParams: () => new URLSearchParams()
}));

describe('Ambiguity Detection, ProfileSwitcher & Teen Handover Suite', () => {
  const householdProfiles: HouseholdProfileMentionTarget[] = [
    {
      id: 'me',
      name: 'Sam Rivera',
      shortName: 'Sam',
      relationship: 'Self',
      colorSlot: 1
    },
    {
      id: 'rosa',
      name: 'Rosa Rivera',
      shortName: 'Rosa',
      relationship: 'Mom',
      colorSlot: 3,
      nicknames: ['Rosita', 'Nana']
    },
    {
      id: 'ava',
      name: 'Ava Rivera',
      shortName: 'Ava',
      relationship: 'Daughter',
      colorSlot: 2
    },
    {
      id: 'leo',
      name: 'Leo Rivera',
      shortName: 'Leo',
      relationship: 'Child',
      colorSlot: 4,
      nicknames: ['Peanut']
    },
    {
      id: 'carlos',
      name: 'Carlos Rivera',
      shortName: 'Carlos',
      relationship: 'Dad',
      colorSlot: 5
    }
  ];

  beforeEach(() => {
    localStorage.clear();
    mockPush.mockClear();
    vi.restoreAllMocks();
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
  });

  afterEach(() => {
    localStorage.clear();
  });

  // ===========================================================================
  // Dimension 1: profileMentions Regex Edge Cases & False Positive Prevention
  // ===========================================================================
  describe('Dimension 1: Pre-Send Ambiguity Detection Regex Invariants', () => {
    it('detects possessives across names and relationship synonyms', () => {
      // Standard ASCII apostrophe
      const match1 = detectProfileAmbiguity("Rosa's lab results came back elevated", 'me', householdProfiles);
      expect(match1).not.toBeNull();
      expect(match1?.targetProfileId).toBe('rosa');

      const match2 = detectProfileAmbiguity("my mom's appointment is at 2pm", 'me', householdProfiles);
      expect(match2).not.toBeNull();
      expect(match2?.targetProfileId).toBe('rosa');

      const match3 = detectProfileAmbiguity("Ava's prescription refill needed", 'me', householdProfiles);
      expect(match3?.targetProfileId).toBe('ava');

      const match4 = detectProfileAmbiguity("Leo's pediatrician follow up", 'me', householdProfiles);
      expect(match4?.targetProfileId).toBe('leo');

      const match5 = detectProfileAmbiguity("Carlos' cardiology summary", 'me', householdProfiles);
      expect(match5?.targetProfileId).toBe('carlos');
    });

    it('detects names even with smart/curly quotation marks (\\u2019)', () => {
      // Smart apostrophe (e.g. from macOS/iOS keyboard)
      const matchSmart = detectProfileAmbiguity("Rosa’s blood pressure readings", 'me', householdProfiles);
      expect(matchSmart).not.toBeNull();
      expect(matchSmart?.targetProfileId).toBe('rosa');
    });

    it('detects nicknames declared on candidate profiles', () => {
      const matchNana = detectProfileAmbiguity("When is Nana next cardiology checkup?", 'me', householdProfiles);
      expect(matchNana?.targetProfileId).toBe('rosa');

      const matchRosita = detectProfileAmbiguity("Rosita needs her insulin refill", 'me', householdProfiles);
      expect(matchRosita?.targetProfileId).toBe('rosa');

      const matchPeanut = detectProfileAmbiguity("Peanut has a mild cough today", 'me', householdProfiles);
      expect(matchPeanut?.targetProfileId).toBe('leo');
    });

    it('detects relationship synonyms without ambiguity', () => {
      expect(detectProfileAmbiguity('My mother has had a fever', 'me', householdProfiles)?.targetProfileId).toBe('rosa');
      expect(detectProfileAmbiguity('Help me find a doctor for my father', 'me', householdProfiles)?.targetProfileId).toBe('carlos');
      expect(detectProfileAmbiguity('My dad broke his wrist', 'me', householdProfiles)?.targetProfileId).toBe('carlos');
      expect(detectProfileAmbiguity('My daughter needs an allergy test', 'me', householdProfiles)?.targetProfileId).toBe('ava');
    });

    it('does NOT trigger false positives on compound words or substring collisions', () => {
      // "Leonardo" contains "Leo" - must NOT match candidate Leo
      expect(detectProfileAmbiguity('Leonardo da Vinci was a painter', 'me', householdProfiles)).toBeNull();

      // "lemon" contains "Leo"
      expect(detectProfileAmbiguity('I drank hot tea with lemon and honey', 'me', householdProfiles)).toBeNull();

      // "lesson" contains "son"
      expect(detectProfileAmbiguity('I learned a valuable lesson in diabetes management', 'me', householdProfiles)).toBeNull();

      // "rosemary" contains "rose"
      expect(detectProfileAmbiguity('Can rosemary oil help with hair thinning?', 'me', householdProfiles)).toBeNull();

      // "kidney" contains "kid"
      expect(detectProfileAmbiguity('Review kidney function blood panel', 'me', householdProfiles)).toBeNull();

      // "boycott" contains "boy"
      expect(detectProfileAmbiguity('Hospital workers planned a boycott', 'me', householdProfiles)).toBeNull();

      // "daughterboard" contains "daughter"
      expect(detectProfileAmbiguity('Replace the monitor daughterboard', 'me', householdProfiles)).toBeNull();

      // "partnership" contains "partner"
      expect(detectProfileAmbiguity('Health system partnership announcement', 'me', householdProfiles)).toBeNull();

      // "brochure" contains "bro"
      expect(detectProfileAmbiguity('I picked up a patient education brochure', 'me', householdProfiles)).toBeNull();
    });

    it('handles heavy punctuation and varied casing', () => {
      expect(detectProfileAmbiguity('Wait... Rosa!', 'me', householdProfiles)?.targetProfileId).toBe('rosa');
      expect(detectProfileAmbiguity('Is ROSA feeling better?', 'me', householdProfiles)?.targetProfileId).toBe('rosa');
      expect(detectProfileAmbiguity('rOsA: new lab results', 'me', householdProfiles)?.targetProfileId).toBe('rosa');
      expect(detectProfileAmbiguity('Questions: 1. Rosa? 2. Diet?', 'me', householdProfiles)?.targetProfileId).toBe('rosa');
    });

    it('guarantees 100% offline execution with zero network calls', () => {
      const fetchSpy = vi.fn().mockImplementation(() => {
        throw new Error('Network call forbidden during ambiguity detection!');
      });
      vi.stubGlobal('fetch', fetchSpy);

      for (let i = 0; i < 50; i++) {
        detectProfileAmbiguity('Check Rosa cardiology notes and Leo prescriptions', 'me', householdProfiles);
      }

      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('does not trigger when active profile refers to their own identity', () => {
      // If Carlos is active and says "I am Dad", do not trigger
      expect(detectProfileAmbiguity("I am Dad and I'm updating my records", 'carlos', householdProfiles)).toBeNull();
      // If Rosa is active and says "I am Rosa"
      expect(detectProfileAmbiguity('I am Rosa', 'rosa', householdProfiles)).toBeNull();
    });
  });

  // ===========================================================================
  // Dimension 2: Hold Card Action Verification in ChatStudioShell
  // ===========================================================================
  describe('Dimension 2: ChatStudioShell Ambiguity Hold Card Actions', () => {
    const fullCareProfiles: CareProfile[] = [
      { id: 'me', name: 'Sam Rivera', relationship: 'Self', role: 'self', colorSlot: 1 },
      { id: 'rosa', name: 'Rosa Rivera', relationship: 'Mom', role: 'guardian', colorSlot: 3, age: 78 },
      { id: 'leo', name: 'Leo Rivera', relationship: 'Child', role: 'guardian', colorSlot: 4, age: 10 }
    ];

    beforeEach(() => {
      saveHouseholdProfiles(fullCareProfiles);
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
    });

    it('holds message and routes to target profile on "Start a chat for [Person]"', async () => {
      render(<ChatStudioShell profileId="me" />);

      const textarea = screen.getByRole('textbox', { name: /message visit steward/i });
      fireEvent.change(textarea, { target: { value: "How is Rosa feeling today?" } });

      const sendBtn = screen.getByRole('button', { name: /send message/i });
      fireEvent.click(sendBtn);

      await waitFor(() => {
        expect(screen.getByText(/this sounds like it's about rosa/i)).toBeInTheDocument();
      });

      const routeBtn = screen.getByRole('button', { name: /start a chat for rosa/i });
      fireEvent.click(routeBtn);

      // Must navigate to Rosa's chat with prompt param
      expect(mockPush).toHaveBeenCalledWith(
        `/p/rosa/chat?prompt=${encodeURIComponent("How is Rosa feeling today?")}`
      );

      // Hold card dismissed
      await waitFor(() => {
        expect(screen.queryByText(/this sounds like it's about rosa/i)).not.toBeInTheDocument();
      });
    });

    it('dismisses held message on "Discard" button click without sending', async () => {
      render(<ChatStudioShell profileId="me" />);

      const textarea = screen.getByRole('textbox', { name: /message visit steward/i });
      fireEvent.change(textarea, { target: { value: "Did Leo take his allergy medicine?" } });

      const sendBtn = screen.getByRole('button', { name: /send message/i });
      fireEvent.click(sendBtn);

      await waitFor(() => {
        expect(screen.getByText(/this sounds like it's about leo/i)).toBeInTheDocument();
      });

      const discardBtn = screen.getByRole('button', { name: /discard/i });
      fireEvent.click(discardBtn);

      await waitFor(() => {
        expect(screen.queryByText(/this sounds like it's about leo/i)).not.toBeInTheDocument();
      });

      // No router push or stream launch
      expect(mockPush).not.toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // Dimension 3: ProfileSwitcher Keyboard, Focus, A11y & Route Sync
  // ===========================================================================
  describe('Dimension 3: ProfileSwitcher Stress Tests', () => {
    const switcherProfiles: CareProfile[] = [
      { id: 'me', name: 'Sam Rivera', relationship: 'Self', role: 'self', colorSlot: 1 },
      { id: 'rosa', name: 'Rosa Rivera', relationship: 'Mom', role: 'guardian', colorSlot: 3, age: 78 },
      { id: 'leo', name: 'Leo Rivera', relationship: 'Child', role: 'guardian', colorSlot: 4, age: 10 }
    ];

    beforeEach(() => {
      saveHouseholdProfiles(switcherProfiles);
    });

    it('requires sequential G then P within 1000ms and ignores when timeout exceeded', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      // Press G, wait 1200ms (> 1000ms), then press P
      vi.useFakeTimers();
      fireEvent.keyDown(window, { key: 'g' });
      vi.advanceTimersByTime(1200);
      fireEvent.keyDown(window, { key: 'p' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      vi.useRealTimers();
    });

    it('ignores G then P if another key is pressed between them', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      // Press 'g', then 'x', then 'p'
      fireEvent.keyDown(window, { key: 'g' });
      fireEvent.keyDown(window, { key: 'x' });
      fireEvent.keyDown(window, { key: 'p' });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('ignores shortcut when modifier keys are held (Cmd/Ctrl/Alt)', () => {
      render(<ProfileSwitcher activeProfileId="me" />);

      // Cmd+G, then Cmd+P (print shortcut)
      fireEvent.keyDown(window, { key: 'g', metaKey: true });
      fireEvent.keyDown(window, { key: 'p', metaKey: true });

      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('does NOT trigger inside contenteditable elements or select elements', () => {
      render(
        <div>
          <div data-testid="editable-div" contentEditable="true" />
          <select data-testid="test-select">
            <option>Option</option>
          </select>
          <ProfileSwitcher activeProfileId="me" />
        </div>
      );

      const editable = screen.getByTestId('editable-div');
      fireEvent.keyDown(editable, { key: 'g' });
      fireEvent.keyDown(editable, { key: 'p' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

      const select = screen.getByTestId('test-select');
      fireEvent.keyDown(select, { key: 'g' });
      fireEvent.keyDown(select, { key: 'p' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });

    it('announces profile switch in polite live region', () => {
      render(<ProfileSwitcher activeProfileId="me" defaultOpen={true} />);

      const liveRegion = screen.getByTestId('profile-switcher-live-region');
      expect(liveRegion).toHaveAttribute('aria-live', 'polite');

      const leoOption = screen.getByTestId('profile-option-leo');
      fireEvent.click(leoOption);

      expect(liveRegion.textContent).toBe('Switched active profile to Leo Rivera');
    });

    it('synchronizes route and preserves arbitrary subpaths', () => {
      expect(switchProfileRoute('/p/me/helpers', 'rosa')).toBe('/p/rosa/helpers');
      expect(switchProfileRoute('/p/rosa/chat', 'leo')).toBe('/p/leo/chat');
      expect(switchProfileRoute('/p/leo/activity', 'me')).toBe('/p/me/activity');
      expect(switchProfileRoute('/p/me/settings/model', 'rosa')).toBe('/p/rosa/settings/model');
      expect(switchProfileRoute('/p/me', 'rosa')).toBe('/p/rosa');

      // Non-scoped routes fallback cleanly to target profile root
      expect(switchProfileRoute('/family', 'rosa')).toBe('/p/rosa');
      expect(switchProfileRoute('/settings/diagnostics', 'leo')).toBe('/p/leo');
      expect(switchProfileRoute('/', 'me')).toBe('/p/me');
    });
  });

  // ===========================================================================
  // Dimension 4: Teen Handover Date Calculation Boundaries
  // ===========================================================================
  describe('Dimension 4: Teen Handover Boundary Calculations', () => {
    it('triggers on exactly the 18th birthday (daysRemaining = 0)', () => {
      // In JavaScript, Date parsing of 'YYYY-MM-DD' parses as UTC, while getFullYear/getDate reads local.
      // Testing exactly on the turning 18 date:
      const profile = { id: 'teen1', dateOfBirth: '2008-10-09' };
      const dob = new Date(profile.dateOfBirth);
      const b18 = new Date(dob.getFullYear() + 18, dob.getMonth(), dob.getDate());
      const refDate = new Date(b18.getTime());

      const status = checkTeenHandoverStatus(profile, refDate);
      expect(status.hasReached18).toBe(true);
      expect(status.isApproaching18).toBe(false);
      expect(status.daysRemaining).toBe(0);
      expect(status.shouldShowReminder).toBe(true);
    });

    it('triggers when within 90 days before 18th birthday', () => {
      // 18th birthday on 2008-11-20
      const profile = { id: 'ava', dateOfBirth: '2008-11-20' };
      const dob = new Date(profile.dateOfBirth);
      const b18 = new Date(dob.getFullYear() + 18, dob.getMonth(), dob.getDate());
      // 45 days before turning 18
      const refDate = new Date(b18.getTime() - 45 * 24 * 60 * 60 * 1000);

      const status = checkTeenHandoverStatus(profile, refDate);
      expect(status.isApproaching18).toBe(true);
      expect(status.hasReached18).toBe(false);
      expect(status.daysRemaining).toBe(45);
      expect(status.shouldShowReminder).toBe(true);
    });

    it('does NOT trigger when > 90 days before 18th birthday', () => {
      // 18th birthday on 2009-04-01
      const profile = { id: 'young-teen', dateOfBirth: '2009-04-01' };
      const dob = new Date(profile.dateOfBirth);
      const b18 = new Date(dob.getFullYear() + 18, dob.getMonth(), dob.getDate());
      // 150 days before turning 18
      const refDate = new Date(b18.getTime() - 150 * 24 * 60 * 60 * 1000);

      const status = checkTeenHandoverStatus(profile, refDate);
      expect(status.isApproaching18).toBe(false);
      expect(status.hasReached18).toBe(false);
      expect(status.shouldShowReminder).toBe(false);
    });

    it('triggers within 90 days after turning 18, but ceases after 90 days past', () => {
      // Turned 18 on 2008-09-01
      const profileInWindow = { id: 'new-adult', dateOfBirth: '2008-09-01' };
      const dobIn = new Date(profileInWindow.dateOfBirth);
      const b18In = new Date(dobIn.getFullYear() + 18, dobIn.getMonth(), dobIn.getDate());
      // 30 days past turning 18
      const refDateIn = new Date(b18In.getTime() + 30 * 24 * 60 * 60 * 1000);

      const statusInWindow = checkTeenHandoverStatus(profileInWindow, refDateIn);
      expect(statusInWindow.hasReached18).toBe(true);
      expect(statusInWindow.shouldShowReminder).toBe(true);

      // 120 days past turning 18
      const refDatePast = new Date(b18In.getTime() + 120 * 24 * 60 * 60 * 1000);
      const statusPastWindow = checkTeenHandoverStatus(profileInWindow, refDatePast);
      expect(statusPastWindow.hasReached18).toBe(false);
      expect(statusPastWindow.shouldShowReminder).toBe(false);
    });

    it('handles leap year birth dates (Feb 29, 2008 -> 2026 non-leap year)', () => {
      // Born on leap day Feb 29, 2008. In 2026 (non-leap), depending on timezone offset, rolls to Feb 28 or Mar 1.
      const leapProfile = { id: 'leap-baby', dateOfBirth: '2008-02-29' };
      const dob = new Date(leapProfile.dateOfBirth);
      const b18 = new Date(dob.getFullYear() + 18, dob.getMonth(), dob.getDate());
      const refDate = new Date(b18.getTime() - 10 * 24 * 60 * 60 * 1000);

      const status = checkTeenHandoverStatus(leapProfile, refDate);
      expect(status.isApproaching18).toBe(true);
      expect(status.turning18Date).toMatch(/(Feb 28|Mar 1), 2026/);
      expect(status.shouldShowReminder).toBe(true);
    });

    it('falls back to age integer when dateOfBirth is missing', () => {
      expect(checkTeenHandoverStatus({ id: 't1', age: 18 }).shouldShowReminder).toBe(true);
      expect(checkTeenHandoverStatus({ id: 't2', age: 17 }).shouldShowReminder).toBe(true);
      expect(checkTeenHandoverStatus({ id: 't3', age: 16 }).shouldShowReminder).toBe(false);
      expect(checkTeenHandoverStatus({ id: 't4', age: 25 }).shouldShowReminder).toBe(false);
    });

    it('gracefully handles missing DOB, missing age, and malformed date strings', () => {
      expect(checkTeenHandoverStatus({ id: 'empty' }).shouldShowReminder).toBe(false);
      expect(checkTeenHandoverStatus({ id: 'bad-date', dateOfBirth: 'invalid-string' }).shouldShowReminder).toBe(false);
    });

    it('suppresses reminder for 30 days when dismissed in local storage', () => {
      const profile = { id: 'dismiss-test', age: 18 };

      // Before dismissal: reminder shows
      expect(checkTeenHandoverStatus(profile).shouldShowReminder).toBe(true);

      // Dismiss reminder
      dismissTeenHandoverReminder('dismiss-test');

      // Immediately after dismissal (< 30 days): reminder suppressed
      expect(checkTeenHandoverStatus(profile).shouldShowReminder).toBe(false);

      // 35 days later: reminder reappears
      const futureDate = new Date(Date.now() + 35 * 24 * 60 * 60 * 1000);
      expect(checkTeenHandoverStatus(profile, futureDate).shouldShowReminder).toBe(true);
    });
  });
});

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
import { render, screen, fireEvent, within } from '@testing-library/react';
import React from 'react';
import FamilyPage from '@/app/family/page';
import {
  saveHouseholdProfiles,
  type CareProfile
} from '@/lib/familyProfiles';

describe('Household Family Management Page (/family)', () => {
  const mockHousehold: CareProfile[] = [
    {
      id: 'me',
      name: 'Sam Rivera',
      relationship: 'Self',
      role: 'self',
      colorSlot: 1,
      stats: { chats: 3, items: 12 }
    },
    {
      id: 'rosa',
      name: 'Rosa Rivera',
      relationship: 'Mom',
      age: 78,
      dateOfBirth: '1948-03-12',
      role: 'guardian',
      colorSlot: 3,
      viewers: ['Dana Rivera'],
      stats: { chats: 7, items: 8 }
    },
    {
      id: 'ava',
      name: 'Ava Rivera',
      relationship: 'Daughter',
      age: 17,
      dateOfBirth: '2008-11-20',
      role: 'guardian',
      colorSlot: 2,
      stats: { chats: 2, items: 4 }
    },
    {
      id: 'leo',
      name: 'Leo Rivera',
      relationship: 'Child',
      age: 10,
      dateOfBirth: '2016-06-15',
      role: 'guardian',
      colorSlot: 4,
      stats: { chats: 4, items: 5 }
    }
  ];

  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles(mockHousehold);
    localStorage.setItem(
      'carefold_viewer_invitations',
      JSON.stringify([
        {
          id: 'inv-dana-1',
          inviteeName: 'Dana Rivera',
          targetProfileId: 'rosa',
          targetProfileName: 'Rosa Rivera',
          permissions: { view_clinical: true, view_paperwork: false },
          expiresInDays: 30,
          inviteCode: 'cf-inv-DANA92',
          createdAt: new Date().toISOString()
        }
      ])
    );
    localStorage.setItem(
      'carefold_share_bundles',
      JSON.stringify([
        {
          id: 'bundle-rosa-init',
          profileId: 'rosa',
          profileName: 'Rosa Rivera',
          title: "Rosa's prep sheet",
          exportedAt: 'Oct 9, 2026'
        }
      ])
    );
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('Group 1: Page Layout & Member Cards', () => {
    it('renders Family page heading, breadcrumbs, and member cards', () => {
      render(<FamilyPage />);

      expect(screen.getByRole('heading', { level: 1, name: 'Family' })).toBeInTheDocument();
      expect(screen.getByText(/People you help care for on this computer/i)).toBeInTheDocument();

      // Check member cards
      const grid = screen.getByTestId('members-grid');
      expect(within(grid).getByText('Sam Rivera')).toBeInTheDocument();
      expect(within(grid).getByText('Rosa Rivera')).toBeInTheDocument();
      expect(within(grid).getByText('Ava Rivera')).toBeInTheDocument();
      expect(within(grid).getByText('Leo Rivera')).toBeInTheDocument();
    });

    it('renders role badges correctly for Self, Guardian, Teen, and Child', () => {
      render(<FamilyPage />);

      const grid = screen.getByTestId('members-grid');
      expect(within(grid).getByText(/Self · you/i)).toBeInTheDocument();
      expect(within(grid).getByText(/You manage/i)).toBeInTheDocument();
      expect(within(grid).getByText(/Teen login/i)).toBeInTheDocument();
      expect(within(grid).getByText(/Child · no login/i)).toBeInTheDocument();
    });

    it('renders chat and item counts on member cards', () => {
      render(<FamilyPage />);

      expect(screen.getByText(/3 chats/i)).toBeInTheDocument();
      expect(screen.getByText(/12 items/i)).toBeInTheDocument();
      expect(screen.getByText(/7 chats/i)).toBeInTheDocument();
      expect(screen.getByText(/8 items/i)).toBeInTheDocument();
    });
  });

  describe('Group 2: Role Matrix Table ("Who can see what")', () => {
    it('renders access governance role matrix with columns for each member', () => {
      render(<FamilyPage />);

      const matrixTable = screen.getByTestId('role-matrix-table');
      expect(matrixTable).toBeInTheDocument();

      expect(within(matrixTable).getByText('Sam (You)')).toBeInTheDocument();
      expect(within(matrixTable).getByText('Rosa')).toBeInTheDocument();
      expect(within(matrixTable).getByText('Ava')).toBeInTheDocument();
      expect(within(matrixTable).getByText('Leo')).toBeInTheDocument();

      // Dana Rivera as viewer row in role matrix
      expect(within(matrixTable).getByText('Dana Rivera')).toBeInTheDocument();
      expect(within(matrixTable).getByText('Viewer · visit prep')).toBeInTheDocument();
    });
  });

  describe('Group 3: Viewer Invitation Flow', () => {
    it('opens invite modal, configures permissions, and submits a new invitation', () => {
      render(<FamilyPage />);

      const inviteBtn = screen.getByTestId('invite-viewer-btn');
      fireEvent.click(inviteBtn);

      const modalTitle = screen.getByText('Invite a Viewer');
      expect(modalTitle).toBeInTheDocument();

      const nameInput = screen.getByTestId('invitee-name-input');
      fireEvent.change(nameInput, { target: { value: 'Carlos Rivera' } });

      const submitBtn = screen.getByTestId('submit-invite-btn');
      fireEvent.click(submitBtn);

      // Verify Carlos added to active viewers list
      const invitationsList = screen.getByTestId('invitations-list');
      expect(within(invitationsList).getByText('Carlos Rivera')).toBeInTheDocument();
    });

    it('revokes an existing invitation when Revoke button is clicked', () => {
      render(<FamilyPage />);

      const invitationsList = screen.getByTestId('invitations-list');
      expect(within(invitationsList).getByText('Dana Rivera')).toBeInTheDocument();
      const revokeBtn = screen.getByTestId('revoke-invite-inv-dana-1');
      fireEvent.click(revokeBtn);

      expect(screen.queryByTestId('invite-row-inv-dana-1')).not.toBeInTheDocument();
      expect(screen.getByText(/No active viewer invitations/i)).toBeInTheDocument();
    });
  });

  describe('Group 4: Local PDF Share Bundle Export', () => {
    it('opens share bundle modal and triggers export', () => {
      render(<FamilyPage />);

      const exportBtn = screen.getByTestId('export-bundle-btn');
      fireEvent.click(exportBtn);

      expect(screen.getByText('Export Care Share Bundle')).toBeInTheDocument();

      const confirmBtn = screen.getByTestId('confirm-export-bundle-btn');
      fireEvent.click(confirmBtn);

      // Verify entry added to bundles list
      expect(screen.getByTestId('bundles-list')).toBeInTheDocument();
    });
  });

  describe('Group 5: Teen Handover Alert on Member Card', () => {
    it('displays teen handover banner for Ava and dismisses it on click', () => {
      render(<FamilyPage />);

      const banner = screen.getByTestId('teen-handover-banner-ava');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText(/Ava turns 18 in/i)).toBeInTheDocument();

      const dismissBtn = within(banner).getByRole('button', { name: /remind me in 30 days/i });
      fireEvent.click(dismissBtn);

      expect(screen.queryByTestId('teen-handover-banner-ava')).not.toBeInTheDocument();
    });
  });
});

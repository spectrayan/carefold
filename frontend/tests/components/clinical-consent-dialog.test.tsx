/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ClinicalConsentDialog } from '@/components/ClinicalConsentDialog';
import type { AgentSummary } from '@/lib/types';

describe('ClinicalConsentDialog Component', () => {
  const clinicalAgent: AgentSummary = {
    id: 'heart-care-coordinator',
    title: 'Cardiology Guide',
    version: '0.1.0',
    risk_class: 'assist',
    skills: ['cardiology-prep'],
    effectiveTools: ['skill-docs'],
    starters: ['Help me prepare for my cardiology visit'],
    description: 'Helps you prepare for heart health appointments.',
    forbidden: ['diagnose', 'prescribe', 'dose', 'replace_emergency_care', 'instruct_stop_medication']
  };

  it('renders the dialog when open with agent title, forbidden actions, and 911/988 emergency guidance', () => {
    render(
      <ClinicalConsentDialog
        isOpen={true}
        agent={clinicalAgent}
        onAccept={vi.fn()}
        onDecline={vi.fn()}
      />
    );
    expect(screen.getByTestId('clinical-consent-dialog')).toBeInTheDocument();
    expect(screen.getByText('Before you chat with Cardiology Guide')).toBeInTheDocument();
    expect(screen.getByTestId('clinical-consent-forbidden-list')).toBeInTheDocument();
    expect(screen.getByTestId('clinical-consent-emergency')).toBeInTheDocument();
    expect(screen.getByTestId('clinical-consent-accept')).toBeInTheDocument();
    expect(screen.getByTestId('clinical-consent-decline')).toBeInTheDocument();
  });

  it('invokes onAccept when acknowledged and I Understand is clicked', () => {
    const onAccept = vi.fn();
    render(
      <ClinicalConsentDialog
        isOpen={true}
        agent={clinicalAgent}
        onAccept={onAccept}
        onDecline={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId('clinical-consent-ack'));
    fireEvent.click(screen.getByTestId('clinical-consent-accept'));
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it('invokes onDecline when Choose Another Agent is clicked', () => {
    const onDecline = vi.fn();
    render(
      <ClinicalConsentDialog
        isOpen={true}
        agent={clinicalAgent}
        onAccept={vi.fn()}
        onDecline={onDecline}
      />
    );
    fireEvent.click(screen.getByTestId('clinical-consent-decline'));
    expect(onDecline).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when closed', () => {
    render(
      <ClinicalConsentDialog
        isOpen={false}
        agent={clinicalAgent}
        onAccept={vi.fn()}
        onDecline={vi.fn()}
      />
    );
    expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument();
  });
});

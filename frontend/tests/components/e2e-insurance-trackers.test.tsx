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

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InsuranceBenefitsCard } from '@/health-ui/InsuranceBenefitsCard';
import type { InsuranceBenefitsDossierData } from '@/lib/types';

const mockInsuranceData: InsuranceBenefitsDossierData = {
  deductible: '$1,500 Individual / $3,000 Family',
  out_of_pocket_maximum: '$4,500 Individual / $9,000 Family',
  coinsurance: '20% after deductible',
  copays: {
    primary_care_visit: '$25',
    specialist_visit: '$50',
    urgent_care: '$40',
    emergency_room: '$250',
    generic_prescription: '$10',
    preferred_brand_prescription: '$35',
  },
  in_out_network_rules:
    'In-network preventive care is covered at 100% without deductible. Out-of-network services require a separate $3,000 deductible with 40% coinsurance.',
  prior_authorization_flags: [
    'Advanced Diagnostic Imaging (MRI, CT, PET)',
    'Specialty Injectable Biologics',
    'Inpatient Hospital Admissions (except emergency)',
    'Outpatient Surgeries & Endoscopies',
  ],
};

describe('E2E Coverage, Claims & Prior-Auth Trackers UI (Feature 9 / Issue #359)', () => {
  it('renders InsuranceBenefitsCard with financial metrics: deductible, OOP max, coinsurance', () => {
    render(
      <InsuranceBenefitsCard
        data={mockInsuranceData}
        agentTitle="Benefits Coordinator"
        isGrounded={true}
      />
    );

    expect(screen.getByTestId('insurance-benefits-card')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Insurance Benefits Summary/i })).toBeInTheDocument();

    // Financial Metrics
    const deductibleCard = screen.getByTestId('metric-deductible');
    expect(deductibleCard).toHaveTextContent('$1,500 Individual / $3,000 Family');

    const oopMaxCard = screen.getByTestId('metric-oop-max');
    expect(oopMaxCard).toHaveTextContent('$4,500 Individual / $9,000 Family');

    const coinsuranceCard = screen.getByTestId('metric-coinsurance');
    expect(coinsuranceCard).toHaveTextContent('20% after deductible');
  });

  it('renders copayments breakdown table with formatted service categories', () => {
    render(<InsuranceBenefitsCard data={mockInsuranceData} />);

    expect(screen.getByTestId('insurance-copays-section')).toBeInTheDocument();
    expect(screen.getByTestId('copays-table')).toBeInTheDocument();

    expect(screen.getByText('Primary Care Visit')).toBeInTheDocument();
    expect(screen.getByText('$25')).toBeInTheDocument();

    expect(screen.getByText('Specialist Visit')).toBeInTheDocument();
    expect(screen.getByText('$50')).toBeInTheDocument();

    expect(screen.getByText('Emergency Room')).toBeInTheDocument();
    expect(screen.getByText('$250')).toBeInTheDocument();
  });

  it('renders network rules and prior authorization requirements with alert styling', () => {
    render(<InsuranceBenefitsCard data={mockInsuranceData} />);

    // In/Out Network Rules
    const networkRules = screen.getByTestId('network-rules');
    expect(networkRules).toBeInTheDocument();
    expect(networkRules).toHaveTextContent(/In-network preventive care is covered at 100%/i);

    // Prior Auth Flags
    const priorAuthSection = screen.getByTestId('prior-auth-flags');
    expect(priorAuthSection).toBeInTheDocument();
    expect(screen.getByText(/Advanced Diagnostic Imaging \(MRI, CT, PET\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Specialty Injectable Biologics/i)).toBeInTheDocument();
    expect(screen.getByText(/Outpatient Surgeries & Endoscopies/i)).toBeInTheDocument();
  });

  it('displays grounded badge, agent attribution, and patient disclaimer banner', () => {
    render(
      <InsuranceBenefitsCard
        data={mockInsuranceData}
        agentTitle="Benefits Coordinator"
        isGrounded={true}
      />
    );

    // Grounded Badge
    const groundedBadge = screen.getByTestId('dossier-grounded-badge');
    expect(groundedBadge).toHaveTextContent('Grounded');

    // Agent Title
    expect(screen.getByText(/Prepared with Benefits Coordinator/i)).toBeInTheDocument();

    // Disclaimer
    const disclaimerBanner = screen.getByTestId('dossier-disclaimer-banner');
    expect(disclaimerBanner).toBeInTheDocument();
  });

  it('handles copy action and triggers clipboard write', async () => {
    const writeTextSpy = vi
      .spyOn(navigator.clipboard, 'writeText')
      .mockResolvedValue(undefined);

    render(<InsuranceBenefitsCard data={mockInsuranceData} />);

    const copyBtn = screen.getByTestId('dossier-copy-btn');
    fireEvent.click(copyBtn);

    expect(writeTextSpy).toHaveBeenCalledTimes(1);
    const copiedText = writeTextSpy.mock.calls[0][0];
    expect(copiedText).toContain('# Health Insurance Benefits Dossier');
    expect(copiedText).toContain('## Financial Cost-Sharing Metrics');
    expect(copiedText).toContain('Primary Care Visit');
    expect(copiedText).toContain('Advanced Diagnostic Imaging');

    writeTextSpy.mockRestore();
  });
});

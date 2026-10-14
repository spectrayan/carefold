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

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { DisclaimerHeader } from '@/components/SafetyDisclaimerBanner';

describe('DisclaimerHeader Component (CF-S05)', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('renders safety notice with required canonical copy', () => {
    render(<DisclaimerHeader />);

    const banner = screen.getByTestId('safety-disclaimer-header');
    expect(banner).toBeInTheDocument();

    expect(banner.textContent?.toLowerCase()).toContain('wellness');
    expect(banner.textContent?.toLowerCase()).toContain('not diagnosis or treatment');
  });

  it('can be dismissed when close button is clicked', () => {
    render(<DisclaimerHeader />);

    const dismissBtn = screen.getByRole('button', { name: /close|dismiss/i });
    expect(dismissBtn).toBeInTheDocument();

    fireEvent.click(dismissBtn);
    expect(screen.queryByTestId('safety-disclaimer-header')).not.toBeInTheDocument();
  });
});

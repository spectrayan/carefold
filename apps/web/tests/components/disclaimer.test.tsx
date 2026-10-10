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

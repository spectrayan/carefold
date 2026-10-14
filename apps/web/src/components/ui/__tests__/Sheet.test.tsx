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

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as React from 'react';
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetClose
} from '../Sheet';

describe('Sheet Primitive', () => {
  it('opens and closes via trigger and close button', () => {
    render(
      <Sheet>
        <SheetTrigger>Open Drawer</SheetTrigger>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Activity Log</SheetTitle>
            <SheetDescription>Recent events</SheetDescription>
          </SheetHeader>
          <SheetClose>Close</SheetClose>
        </SheetContent>
      </Sheet>
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /open drawer/i }));

    const sheet = screen.getByRole('dialog');
    expect(sheet).toBeInTheDocument();
    expect(sheet).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('Activity Log')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders bottom sheet with grab handle', () => {
    render(
      <Sheet defaultOpen side="bottom">
        <SheetContent>
          <SheetTitle>Profile Switcher</SheetTitle>
        </SheetContent>
      </Sheet>
    );

    const sheet = screen.getByRole('dialog');
    expect(sheet).toBeInTheDocument();
    expect(sheet.querySelector('.rounded-full')).toBeInTheDocument();
  });

  it('closes on Escape key press', () => {
    render(
      <Sheet defaultOpen>
        <SheetContent>
          <SheetTitle>Escapable Sheet</SheetTitle>
        </SheetContent>
      </Sheet>
    );

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

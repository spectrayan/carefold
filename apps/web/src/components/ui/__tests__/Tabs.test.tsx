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
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../Tabs';

describe('Tabs Primitive', () => {
  it('renders tablist, tabs, and panels with proper ARIA attributes', () => {
    render(
      <Tabs defaultValue="account">
        <TabsList aria-label="Settings Tabs">
          <TabsTrigger value="account">Account</TabsTrigger>
          <TabsTrigger value="password">Password</TabsTrigger>
        </TabsList>
        <TabsContent value="account">Account Settings Panel</TabsContent>
        <TabsContent value="password">Password Settings Panel</TabsContent>
      </Tabs>
    );

    const tablist = screen.getByRole('tablist', { name: /settings tabs/i });
    expect(tablist).toBeInTheDocument();

    const accountTab = screen.getByRole('tab', { name: /account/i });
    const passwordTab = screen.getByRole('tab', { name: /password/i });

    expect(accountTab).toHaveAttribute('aria-selected', 'true');
    expect(accountTab).toHaveAttribute('tabIndex', '0');

    expect(passwordTab).toHaveAttribute('aria-selected', 'false');
    expect(passwordTab).toHaveAttribute('tabIndex', '-1');

    expect(screen.getByRole('tabpanel')).toHaveTextContent('Account Settings Panel');
  });

  it('switches active panel on tab click', () => {
    render(
      <Tabs defaultValue="first">
        <TabsList>
          <TabsTrigger value="first">First</TabsTrigger>
          <TabsTrigger value="second">Second</TabsTrigger>
        </TabsList>
        <TabsContent value="first">Panel One</TabsContent>
        <TabsContent value="second">Panel Two</TabsContent>
      </Tabs>
    );

    expect(screen.getByText('Panel One')).toBeInTheDocument();
    expect(screen.queryByText('Panel Two')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /second/i }));

    expect(screen.queryByText('Panel One')).not.toBeInTheDocument();
    expect(screen.getByText('Panel Two')).toBeInTheDocument();
  });

  it('navigates tabs with ArrowRight and ArrowLeft keys and wraps around', () => {
    render(
      <Tabs defaultValue="tab1">
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
          <TabsTrigger value="tab2">Tab 2</TabsTrigger>
          <TabsTrigger value="tab3">Tab 3</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1">Content 1</TabsContent>
        <TabsContent value="tab2">Content 2</TabsContent>
        <TabsContent value="tab3">Content 3</TabsContent>
      </Tabs>
    );

    const list = screen.getByRole('tablist');
    const tab1 = screen.getByRole('tab', { name: /tab 1/i });
    tab1.focus();

    // ArrowRight to Tab 2
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /tab 2/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Content 2')).toBeInTheDocument();

    // ArrowRight to Tab 3
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /tab 3/i })).toHaveAttribute('aria-selected', 'true');

    // ArrowRight wraps to Tab 1
    fireEvent.keyDown(list, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: /tab 1/i })).toHaveAttribute('aria-selected', 'true');

    // ArrowLeft wraps to Tab 3
    fireEvent.keyDown(list, { key: 'ArrowLeft' });
    expect(screen.getByRole('tab', { name: /tab 3/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('jumps to first/last tab on Home and End keys', () => {
    render(
      <Tabs defaultValue="tab2">
        <TabsList>
          <TabsTrigger value="tab1">Tab 1</TabsTrigger>
          <TabsTrigger value="tab2">Tab 2</TabsTrigger>
          <TabsTrigger value="tab3">Tab 3</TabsTrigger>
        </TabsList>
        <TabsContent value="tab1">Content 1</TabsContent>
        <TabsContent value="tab2">Content 2</TabsContent>
        <TabsContent value="tab3">Content 3</TabsContent>
      </Tabs>
    );

    const list = screen.getByRole('tablist');

    // Home to Tab 1
    fireEvent.keyDown(list, { key: 'Home' });
    expect(screen.getByRole('tab', { name: /tab 1/i })).toHaveAttribute('aria-selected', 'true');

    // End to Tab 3
    fireEvent.keyDown(list, { key: 'End' });
    expect(screen.getByRole('tab', { name: /tab 3/i })).toHaveAttribute('aria-selected', 'true');
  });

  it('supports badges on tab triggers', () => {
    render(
      <Tabs defaultValue="t1">
        <TabsList>
          <TabsTrigger value="t1" badge={5}>Messages</TabsTrigger>
        </TabsList>
        <TabsContent value="t1">Messages List</TabsContent>
      </Tabs>
    );

    expect(screen.getByText('5')).toBeInTheDocument();
  });
});

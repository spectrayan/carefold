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
import * as React from 'react';
import {
  Menu,
  MenuTrigger,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuLabel
} from '../Menu';

describe('Menu Primitive', () => {
  it('opens on trigger click and renders menu and menuitems', () => {
    const handleEdit = vi.fn();
    render(
      <Menu>
        <MenuTrigger>Options</MenuTrigger>
        <MenuContent>
          <MenuLabel>Actions</MenuLabel>
          <MenuItem onClick={handleEdit}>Edit</MenuItem>
          <MenuSeparator />
          <MenuItem destructive>Delete</MenuItem>
        </MenuContent>
      </Menu>
    );

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /options/i }));

    const menu = screen.getByRole('menu');
    expect(menu).toBeInTheDocument();

    const editItem = screen.getByRole('menuitem', { name: /edit/i });
    expect(editItem).toBeInTheDocument();

    const deleteItem = screen.getByRole('menuitem', { name: /delete/i });
    expect(deleteItem).toBeInTheDocument();

    fireEvent.click(editItem);
    expect(handleEdit).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('navigates menuitems with ArrowDown and ArrowUp and wraps', () => {
    render(
      <Menu defaultOpen>
        <MenuTrigger>Trigger</MenuTrigger>
        <MenuContent>
          <MenuItem>First</MenuItem>
          <MenuItem>Second</MenuItem>
          <MenuItem>Third</MenuItem>
        </MenuContent>
      </Menu>
    );

    const menu = screen.getByRole('menu');
    const first = screen.getByRole('menuitem', { name: /first/i });
    const second = screen.getByRole('menuitem', { name: /second/i });
    const third = screen.getByRole('menuitem', { name: /third/i });

    first.focus();
    expect(document.activeElement).toBe(first);

    // ArrowDown to Second
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(second);

    // ArrowDown to Third
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(third);

    // ArrowDown wraps to First
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(first);

    // ArrowUp wraps to Third
    fireEvent.keyDown(menu, { key: 'ArrowUp' });
    expect(document.activeElement).toBe(third);
  });

  it('supports Home and End keys to jump to first/last item', () => {
    render(
      <Menu defaultOpen>
        <MenuTrigger>Trigger</MenuTrigger>
        <MenuContent>
          <MenuItem>Alpha</MenuItem>
          <MenuItem>Beta</MenuItem>
          <MenuItem>Gamma</MenuItem>
        </MenuContent>
      </Menu>
    );

    const menu = screen.getByRole('menu');
    const alpha = screen.getByRole('menuitem', { name: /alpha/i });
    const gamma = screen.getByRole('menuitem', { name: /gamma/i });

    fireEvent.keyDown(menu, { key: 'End' });
    expect(document.activeElement).toBe(gamma);

    fireEvent.keyDown(menu, { key: 'Home' });
    expect(document.activeElement).toBe(alpha);
  });

  it('closes menu on Escape key press', () => {
    render(
      <Menu defaultOpen>
        <MenuTrigger>Trigger</MenuTrigger>
        <MenuContent>
          <MenuItem>Item</MenuItem>
        </MenuContent>
      </Menu>
    );

    const menu = screen.getByRole('menu');
    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});

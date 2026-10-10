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
import { Segmented, SegmentedOption } from '../Segmented';

describe('Segmented Primitive', () => {
  const options: SegmentedOption[] = [
    { value: 'helpers', label: 'Helpers', badge: 12 },
    { value: 'skills', label: 'Skills', badge: 24 },
    { value: 'archived', label: 'Archived', disabled: true }
  ];

  it('renders radiogroup and options with aria-checked states', () => {
    const handleChange = vi.fn();
    render(
      <Segmented
        aria-label="View toggle"
        options={options}
        value="helpers"
        onChange={handleChange}
      />
    );

    const group = screen.getByRole('radiogroup', { name: /view toggle/i });
    expect(group).toBeInTheDocument();

    const helpersRadio = screen.getByRole('radio', { name: /helpers/i });
    const skillsRadio = screen.getByRole('radio', { name: /skills/i });
    const archivedRadio = screen.getByRole('radio', { name: /archived/i });

    expect(helpersRadio).toHaveAttribute('aria-checked', 'true');
    expect(helpersRadio).toHaveAttribute('tabIndex', '0');

    expect(skillsRadio).toHaveAttribute('aria-checked', 'false');
    expect(skillsRadio).toHaveAttribute('tabIndex', '-1');

    expect(archivedRadio).toBeDisabled();
  });

  it('calls onChange when clicking an enabled option', () => {
    const handleChange = vi.fn();
    render(
      <Segmented
        aria-label="View toggle"
        options={options}
        value="helpers"
        onChange={handleChange}
      />
    );

    fireEvent.click(screen.getByRole('radio', { name: /skills/i }));
    expect(handleChange).toHaveBeenCalledWith('skills');
  });

  it('does not call onChange when clicking a disabled option', () => {
    const handleChange = vi.fn();
    render(
      <Segmented
        aria-label="View toggle"
        options={options}
        value="helpers"
        onChange={handleChange}
      />
    );

    fireEvent.click(screen.getByRole('radio', { name: /archived/i }));
    expect(handleChange).not.toHaveBeenCalled();
  });

  it('navigates with arrow keys and skips disabled options', () => {
    function ControlledSegmented() {
      const [val, setVal] = React.useState('helpers');
      return (
        <Segmented
          aria-label="View toggle"
          options={options}
          value={val}
          onChange={setVal}
        />
      );
    }

    render(<ControlledSegmented />);
    const group = screen.getByRole('radiogroup');

    // ArrowRight to skills
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(screen.getByRole('radio', { name: /skills/i })).toHaveAttribute('aria-checked', 'true');

    // ArrowRight wraps back to helpers (skipping archived which is disabled)
    fireEvent.keyDown(group, { key: 'ArrowRight' });
    expect(screen.getByRole('radio', { name: /helpers/i })).toHaveAttribute('aria-checked', 'true');
  });
});

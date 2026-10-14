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
import { Avatar, getInitials, hashNameToSlot } from '../Avatar';

describe('Avatar Primitive', () => {
  describe('getInitials', () => {
    it('extracts two letters from first and last name', () => {
      expect(getInitials('Rosa Rivera')).toBe('RR');
      expect(getInitials('John Doe')).toBe('JD');
    });

    it('extracts first two letters from single word name', () => {
      expect(getInitials('Sam')).toBe('SA');
      expect(getInitials('Al')).toBe('AL');
    });

    it('handles edge cases gracefully', () => {
      expect(getInitials('')).toBe('?');
      expect(getInitials('   ')).toBe('?');
    });
  });

  describe('hashNameToSlot', () => {
    it('deterministically hashes name to slot 1-5', () => {
      const slot1 = hashNameToSlot('Rosa Rivera');
      const slot2 = hashNameToSlot('Rosa Rivera');
      expect(slot1).toBe(slot2);
      expect(slot1).toBeGreaterThanOrEqual(1);
      expect(slot1).toBeLessThanOrEqual(5);
    });
  });

  describe('Avatar Component', () => {
    it('renders initials with accessible role and aria-label', () => {
      render(<Avatar name="Rosa Rivera" />);
      const avatar = screen.getByRole('img', { name: /rosa rivera/i });
      expect(avatar).toBeInTheDocument();
      expect(avatar).toHaveTextContent('RR');
    });

    it('renders with specified color slot', () => {
      render(<Avatar name="Leo" colorSlot={3} />);
      const avatar = screen.getByRole('img', { name: /leo/i });
      expect(avatar).toHaveClass('bg-[var(--cf-member-3-bg)]');
    });

    it('renders image when src is valid', () => {
      render(<Avatar name="Sam" src="https://example.com/avatar.png" alt="Sam Profile" />);
      const img = screen.getByRole('img', { name: /sam profile/i });
      expect(img).toBeInTheDocument();
    });

    it('falls back to initials when image errors', () => {
      render(<Avatar name="Sam Smith" src="https://invalid.com/err.png" />);
      const img = screen.getByRole('img', { name: /sam smith/i });
      expect(img).toBeInTheDocument();

      fireEvent.error(img);
      expect(screen.getByText('SS')).toBeInTheDocument();
    });
  });
});

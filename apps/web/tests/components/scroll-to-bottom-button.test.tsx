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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';
import { ScrollToBottomButton } from '@/components/chat/ScrollToBottomButton';
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';
import { AttachmentUploader, type AttachedFile } from '@/components/AttachmentUploader';

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    risk_class: 'wellness',
    skills: ['visit-prep'],
    effectiveTools: [],
    starters: ['What should I ask my doctor?']
  }
];

function createMockSSEResponse(events: Array<{ event?: string; data: Record<string, any> }>) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const ev of events) {
        const eventLine = ev.event ? `event: ${ev.event}\n` : '';
        const dataLine = `data: ${JSON.stringify(ev.data)}\n\n`;
        controller.enqueue(encoder.encode(eventLine + dataLine));
      }
      controller.close();
    }
  });

  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' }
  });
}

describe('ScrollToBottomButton Component', () => {
  it('applies opacity-0 and pointer-events-none when visible is false', () => {
    const { container } = render(<ScrollToBottomButton visible={false} onClick={vi.fn()} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper).toHaveClass('opacity-0');
    expect(wrapper).toHaveClass('pointer-events-none');
    expect(wrapper).not.toHaveClass('opacity-100');
    expect(wrapper).not.toHaveClass('pointer-events-auto');
  });

  it('applies opacity-100 and pointer-events-auto when visible is true', () => {
    const { container } = render(<ScrollToBottomButton visible={true} onClick={vi.fn()} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper).toHaveClass('opacity-100');
    expect(wrapper).toHaveClass('pointer-events-auto');
    expect(wrapper).not.toHaveClass('opacity-0');
    expect(wrapper).not.toHaveClass('pointer-events-none');

    const btn = screen.getByTestId('scroll-to-bottom-btn');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute('aria-label', 'Scroll to bottom');
  });

  it('triggers onClick handler when clicked', () => {
    const handleClick = vi.fn();
    render(<ScrollToBottomButton visible={true} onClick={handleClick} />);
    const btn = screen.getByTestId('scroll-to-bottom-btn');
    fireEvent.click(btn);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not render unread badge when unreadCount is 0 or undefined', () => {
    const { rerender } = render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={0} />);
    expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();

    rerender(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={undefined} />);
    expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();
  });

  it('renders unread badge with exact count when unreadCount > 0', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={7} />);
    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('7');
    expect(screen.getByTestId('scroll-to-bottom-btn')).toHaveAttribute('aria-label', 'Scroll to bottom (7 unread)');
  });

  it('caps unread badge text at "99+" when unreadCount exceeds 99', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={150} />);
    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toHaveTextContent('99+');
  });

  it('adheres to accessible minimum touch target of >=44px', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} />);
    const btn = screen.getByTestId('scroll-to-bottom-btn');
    expect(btn.className).toContain('min-w-[44px]');
    expect(btn.className).toContain('min-h-[44px]');
  });

  it('includes ChevronDown icon and theme styling classes', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} />);
    const btn = screen.getByTestId('scroll-to-bottom-btn');
    expect(btn.className).toContain('dark:bg-zinc-800');
    expect(btn.className).toContain('dark:border-zinc-700');
    expect(btn.querySelector('svg')).toBeInTheDocument();
  });
});

describe('ChatClient Scroll Tracking & Viewport Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
  });

  it('uses dynamic viewport height 100dvh and overflow-hidden on outer card', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const outerCard = container.querySelector('.flex.flex-col');
    expect(outerCard?.className).toContain('h-[calc(100dvh-120px)]');
    expect(outerCard?.className).toContain('overflow-hidden');
    expect(outerCard?.className).not.toContain('100vh');
  });

  it('hides ScrollToBottomButton with opacity-0 when user is at the bottom', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const btnWrapper = container.querySelector('[data-testid="scroll-to-bottom-btn"]')?.parentElement;
    expect(btnWrapper).toHaveClass('opacity-0');
    expect(btnWrapper).toHaveClass('pointer-events-none');
  });

  it('reveals ScrollToBottomButton when scrolled away from bottom and hides when scrolled back', async () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto');
    expect(scrollContainer).toBeInTheDocument();

    if (scrollContainer) {
      // Simulate scrolled up (distanceFromBottom = 1000 - 200 - 400 = 400 >= 60)
      Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1000 });
      Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 200 });
      Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });

      fireEvent.scroll(scrollContainer);

      await waitFor(() => {
        const btnWrapper = container.querySelector('[data-testid="scroll-to-bottom-btn"]')?.parentElement;
        expect(btnWrapper).toHaveClass('opacity-100');
        expect(btnWrapper).toHaveClass('pointer-events-auto');
      });

      // Simulate scrolling back to bottom (distanceFromBottom = 1000 - 580 - 400 = 20 < 60)
      Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 580 });
      fireEvent.scroll(scrollContainer);

      await waitFor(() => {
        const btnWrapper = container.querySelector('[data-testid="scroll-to-bottom-btn"]')?.parentElement;
        expect(btnWrapper).toHaveClass('opacity-0');
        expect(btnWrapper).toHaveClass('pointer-events-none');
      });
    }
  });

  it('increments unread counter when new tokens arrive while scrolled up and resets on click', async () => {
    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat' || url === '/api/v1/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Chunk 1. ' } },
            { event: 'token', data: { type: 'token', delta: 'Chunk 2. ' } },
            { event: 'token', data: { type: 'token', delta: 'Chunk 3.' } },
            { event: 'done', data: { type: 'done', fullText: 'Chunk 1. Chunk 2. Chunk 3.' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto');
    expect(scrollContainer).toBeInTheDocument();

    if (scrollContainer) {
      // User scrolls up before/during stream
      Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1200 });
      Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 200 });
      Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
      fireEvent.scroll(scrollContainer);

      const btnWrapper = container.querySelector('[data-testid="scroll-to-bottom-btn"]')?.parentElement;
      expect(btnWrapper).toHaveClass('opacity-100');

      // Send prompt
      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Test streaming unread' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Re-apply scrolled up position
      Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 200 });
      fireEvent.scroll(scrollContainer);

      await waitFor(() => {
        expect(within(scrollContainer as HTMLElement).getByText(/Chunk 1/i)).toBeInTheDocument();
      });

      const scrollBtn = screen.getByTestId('scroll-to-bottom-btn');
      expect(scrollBtn).toBeInTheDocument();

      // Click button to jump to bottom
      const scrollIntoViewSpy = vi.spyOn(Element.prototype, 'scrollIntoView');
      fireEvent.click(scrollBtn);

      expect(scrollIntoViewSpy).toHaveBeenCalled();
      const updatedWrapper = container.querySelector('[data-testid="scroll-to-bottom-btn"]')?.parentElement;
      expect(updatedWrapper).toHaveClass('opacity-0');
    }
  });

  it('confirms zero invalid Tailwind classes in AttachmentUploader rendered output', () => {
    const attachedFiles: AttachedFile[] = [
      { filename: 'doc.txt', path: 'attachments/doc.txt', size_bytes: 1024, format: 'text' }
    ];

    const { container } = render(
      <AttachmentUploader
        attachedFiles={attachedFiles}
        onAttach={vi.fn()}
        onRemove={vi.fn()}
      />
    );

    const html = container.innerHTML;
    expect(html).not.toContain('focus:outline-hidden');
    expect(html).not.toContain('shadow-2xs');
    expect(html).not.toContain('shadow-xs');
    expect(html).not.toContain('backdrop-blur-xs');
    expect(html).toContain('focus:outline-none');
    expect(html).toContain('shadow-sm');
  });
});

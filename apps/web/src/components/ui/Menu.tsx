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

'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

interface MenuContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  menuId: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  contentRef: React.RefObject<HTMLDivElement | null>;
}

const MenuContext = React.createContext<MenuContextValue | null>(null);

function useMenuContext() {
  const context = React.useContext(MenuContext);
  if (!context) {
    throw new Error('Menu compound components must be rendered within a <Menu>');
  }
  return context;
}

export interface MenuProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function Menu({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children
}: MenuProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const contentRef = React.useRef<HTMLDivElement | null>(null);
  const menuId = React.useId();

  const handleOpenChange = React.useCallback(
    (newOpen: boolean) => {
      if (!isControlled) {
        setUncontrolledOpen(newOpen);
      }
      onOpenChange?.(newOpen);
    },
    [isControlled, onOpenChange]
  );

  return (
    <MenuContext.Provider
      value={{
        open: isOpen,
        onOpenChange: handleOpenChange,
        menuId,
        triggerRef,
        contentRef
      }}
    >
      <div className="relative inline-block text-left">{children}</div>
    </MenuContext.Provider>
  );
}

export interface MenuTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const MenuTrigger = React.forwardRef<HTMLButtonElement, MenuTriggerProps>(
  ({ children, onClick, onKeyDown, className, ...props }, ref) => {
    const { open, onOpenChange, menuId, triggerRef, contentRef } = useMenuContext();

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      onOpenChange(!open);
      onClick?.(e);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onOpenChange(true);
        setTimeout(() => {
          const first = contentRef.current?.querySelector<HTMLElement>(
            '[role="menuitem"]:not([disabled])'
          );
          first?.focus();
        }, 10);
      }
      onKeyDown?.(e);
    };

    return (
      <button
        ref={(el) => {
          triggerRef.current = el;
          if (typeof ref === 'function') ref(el);
          else if (ref) ref.current = el;
        }}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={`menu-${menuId}`}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        className={className}
        {...props}
      >
        {children}
      </button>
    );
  }
);
MenuTrigger.displayName = 'MenuTrigger';

export interface MenuContentProps extends React.HTMLAttributes<HTMLDivElement> {
  align?: 'start' | 'end';
}

export const MenuContent = React.forwardRef<HTMLDivElement, MenuContentProps>(
  ({ align = 'start', className, children, ...props }, ref) => {
    const { open, onOpenChange, menuId, triggerRef, contentRef } = useMenuContext();
    const typeaheadBufferRef = React.useRef('');
    const typeaheadTimerRef = React.useRef<NodeJS.Timeout | null>(null);

    React.useEffect(() => {
      if (!open) return;

      const handleMouseDown = (e: MouseEvent) => {
        const target = e.target as Node;
        if (
          contentRef.current &&
          !contentRef.current.contains(target) &&
          triggerRef.current &&
          !triggerRef.current.contains(target)
        ) {
          onOpenChange(false);
        }
      };

      document.addEventListener('mousedown', handleMouseDown);
      return () => document.removeEventListener('mousedown', handleMouseDown);
    }, [open, onOpenChange, triggerRef, contentRef]);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
      const container = contentRef.current;
      if (!container) return;

      const items = Array.from(
        container.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])')
      );
      if (items.length === 0) return;

      const currentIndex = items.indexOf(document.activeElement as HTMLElement);

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
        items[nextIndex].focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
        items[prevIndex].focus();
      } else if (e.key === 'Home') {
        e.preventDefault();
        items[0].focus();
      } else if (e.key === 'End') {
        e.preventDefault();
        items[items.length - 1].focus();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onOpenChange(false);
        triggerRef.current?.focus();
      } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        // Typeahead search
        if (typeaheadTimerRef.current) clearTimeout(typeaheadTimerRef.current);
        typeaheadBufferRef.current += e.key.toLowerCase();
        typeaheadTimerRef.current = setTimeout(() => {
          typeaheadBufferRef.current = '';
        }, 500);

        const search = typeaheadBufferRef.current;
        const match = items.find((item) =>
          item.textContent?.trim().toLowerCase().startsWith(search)
        );
        if (match) {
          match.focus();
        }
      }
    };

    if (!open) return null;

    return (
      <div
        ref={(el) => {
          contentRef.current = el;
          if (typeof ref === 'function') ref(el);
          else if (ref) ref.current = el;
        }}
        id={`menu-${menuId}`}
        role="menu"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={cn(
          'absolute z-[var(--cf-z-popover)] mt-1 min-w-[12rem] rounded-[var(--cf-radius-md)] p-1',
          'bg-[var(--cf-surface)] text-[var(--cf-fg)] shadow-2 border border-[var(--cf-border)]',
          'focus:outline-none transition-all',
          align === 'end' ? 'right-0' : 'left-0',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
MenuContent.displayName = 'MenuContent';

export interface MenuItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  destructive?: boolean;
  icon?: React.ReactNode;
}

export const MenuItem = React.forwardRef<HTMLButtonElement, MenuItemProps>(
  (
    {
      destructive = false,
      icon,
      children,
      className,
      onClick,
      disabled,
      ...props
    },
    ref
  ) => {
    const { onOpenChange, triggerRef } = useMenuContext();

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      if (disabled) return;
      onClick?.(e);
      onOpenChange(false);
      triggerRef.current?.focus();
    };

    return (
      <button
        ref={ref}
        role="menuitem"
        type="button"
        disabled={disabled}
        onClick={handleClick}
        className={cn(
          'w-full text-left font-medium text-sm flex items-center gap-2 px-3 py-2 rounded-[var(--cf-radius-sm)] select-none transition-colors min-h-[36px]',
          'focus-visible:outline-none focus:bg-[var(--cf-surface-2)] active:bg-[var(--cf-surface-3)]',
          'disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none',
          destructive
            ? 'text-[var(--cf-danger-fg)] hover:bg-[var(--cf-danger-bg)] focus:bg-[var(--cf-danger-bg)]'
            : 'text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)]',
          className
        )}
        {...props}
      >
        {icon && <span className="inline-flex shrink-0">{icon}</span>}
        <span className="flex-1 truncate">{children}</span>
      </button>
    );
  }
);
MenuItem.displayName = 'MenuItem';

export interface MenuSeparatorProps extends React.HTMLAttributes<HTMLDivElement> {}

export const MenuSeparator = React.forwardRef<HTMLDivElement, MenuSeparatorProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="separator"
      className={cn('my-1 h-px bg-[var(--cf-border)]', className)}
      {...props}
    />
  )
);
MenuSeparator.displayName = 'MenuSeparator';

export interface MenuLabelProps extends React.HTMLAttributes<HTMLDivElement> {}

export const MenuLabel = React.forwardRef<HTMLDivElement, MenuLabelProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('px-3 py-1.5 text-xs font-semibold text-[var(--cf-fg-subtle)] uppercase tracking-wider', className)}
      {...props}
    />
  )
);
MenuLabel.displayName = 'MenuLabel';

export interface MenuGroupProps extends React.HTMLAttributes<HTMLDivElement> {}

export const MenuGroup = React.forwardRef<HTMLDivElement, MenuGroupProps>(
  ({ className, ...props }, ref) => (
    <div ref={ref} role="group" className={cn('space-y-0.5', className)} {...props} />
  )
);
MenuGroup.displayName = 'MenuGroup';

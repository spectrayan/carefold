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

export type SheetSide = 'bottom' | 'right' | 'left';

interface SheetContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side: SheetSide;
  sheetId: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const SheetContext = React.createContext<SheetContextValue | null>(null);

function useSheetContext() {
  const context = React.useContext(SheetContext);
  if (!context) {
    throw new Error('Sheet compound components must be rendered within a <Sheet>');
  }
  return context;
}

export interface SheetProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: SheetSide;
  children: React.ReactNode;
}

export function Sheet({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  side = 'right',
  children
}: SheetProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const sheetId = React.useId();

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
    <SheetContext.Provider
      value={{
        open: isOpen,
        onOpenChange: handleOpenChange,
        side,
        sheetId,
        triggerRef
      }}
    >
      {children}
    </SheetContext.Provider>
  );
}

export interface SheetTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const SheetTrigger = React.forwardRef<HTMLButtonElement, SheetTriggerProps>(
  ({ children, onClick, className, ...props }, ref) => {
    const { open, onOpenChange, triggerRef } = useSheetContext();

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      onOpenChange(!open);
      onClick?.(e);
    };

    return (
      <button
        ref={(el) => {
          triggerRef.current = el;
          if (typeof ref === 'function') ref(el);
          else if (ref) ref.current = el;
        }}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={handleClick}
        className={className}
        {...props}
      >
        {children}
      </button>
    );
  }
);
SheetTrigger.displayName = 'SheetTrigger';

export interface SheetContentProps extends React.HTMLAttributes<HTMLDivElement> {
  showGrabHandle?: boolean;
}

const sideStyles: Record<SheetSide, string> = {
  right: 'fixed inset-y-0 right-0 h-full w-full max-w-md border-l border-[var(--cf-border)] rounded-l-[var(--cf-radius-xl)]',
  left: 'fixed inset-y-0 left-0 h-full w-full max-w-md border-r border-[var(--cf-border)] rounded-r-[var(--cf-radius-xl)]',
  bottom: 'fixed inset-x-0 bottom-0 w-full max-h-[90dvh] border-t border-[var(--cf-border)] rounded-t-[var(--cf-radius-xl)]'
};

export const SheetContent = React.forwardRef<HTMLDivElement, SheetContentProps>(
  ({ showGrabHandle, className, children, ...props }, ref) => {
    const { open, onOpenChange, side, sheetId, triggerRef } = useSheetContext();
    const contentRef = React.useRef<HTMLDivElement | null>(null);
    const prevActiveElementRef = React.useRef<HTMLElement | null>(null);

    React.useEffect(() => {
      if (!open) return;

      prevActiveElementRef.current = document.activeElement as HTMLElement | null;

      const container = contentRef.current;
      if (!container) return;

      const focusableSelector =
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

      const focusables = Array.from(
        container.querySelectorAll<HTMLElement>(focusableSelector)
      );

      if (focusables.length > 0) {
        focusables[0].focus();
      } else {
        container.focus();
      }

      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          onOpenChange(false);
          return;
        }

        if (e.key === 'Tab') {
          const currentFocusables = Array.from(
            container.querySelectorAll<HTMLElement>(focusableSelector)
          );
          if (currentFocusables.length === 0) {
            e.preventDefault();
            return;
          }

          const first = currentFocusables[0];
          const last = currentFocusables[currentFocusables.length - 1];

          if (e.shiftKey) {
            if (document.activeElement === first) {
              e.preventDefault();
              last.focus();
            }
          } else {
            if (document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }
      };

      document.addEventListener('keydown', handleKeyDown);

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        const restoreEl = triggerRef.current || prevActiveElementRef.current;
        restoreEl?.focus?.();
      };
    }, [open, onOpenChange, triggerRef]);

    if (!open) return null;

    const renderGrabHandle = showGrabHandle ?? side === 'bottom';

    return (
      <div className="fixed inset-0 z-[var(--cf-z-modal)]" role="presentation">
        {/* Backdrop Scrim */}
        <div
          className="fixed inset-0 bg-[var(--cf-overlay)] backdrop-blur-sm transition-opacity"
          aria-hidden="true"
          onClick={() => onOpenChange(false)}
        />

        {/* Sheet Surface */}
        <div
          ref={(el) => {
            contentRef.current = el;
            if (typeof ref === 'function') ref(el);
            else if (ref) ref.current = el;
          }}
          role="dialog"
          aria-modal="true"
          aria-labelledby={`sheet-title-${sheetId}`}
          aria-describedby={`sheet-desc-${sheetId}`}
          tabIndex={-1}
          className={cn(
            'bg-[var(--cf-surface)] p-6 shadow-3 overflow-y-auto focus:outline-none transition-transform',
            sideStyles[side],
            className
          )}
          {...props}
        >
          {renderGrabHandle && (
            <div
              className="w-10 h-1.5 rounded-full bg-[var(--cf-border-strong)] mx-auto mb-4 opacity-60 shrink-0"
              aria-hidden="true"
            />
          )}
          {children}
        </div>
      </div>
    );
  }
);
SheetContent.displayName = 'SheetContent';

export interface SheetHeaderProps extends React.HTMLAttributes<HTMLDivElement> {}

export const SheetHeader = React.forwardRef<HTMLDivElement, SheetHeaderProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col space-y-1.5 pb-4 text-left', className)}
      {...props}
    />
  )
);
SheetHeader.displayName = 'SheetHeader';

export interface SheetTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  as?: 'h1' | 'h2' | 'h3' | 'h4';
}

export const SheetTitle = React.forwardRef<HTMLHeadingElement, SheetTitleProps>(
  ({ as: Component = 'h2', className, ...props }, ref) => {
    const { sheetId } = useSheetContext();
    return (
      <Component
        ref={ref}
        id={`sheet-title-${sheetId}`}
        className={cn('text-lg font-semibold leading-none tracking-tight text-[var(--cf-fg)]', className)}
        {...props}
      />
    );
  }
);
SheetTitle.displayName = 'SheetTitle';

export interface SheetDescriptionProps extends React.HTMLAttributes<HTMLParagraphElement> {}

export const SheetDescription = React.forwardRef<HTMLParagraphElement, SheetDescriptionProps>(
  ({ className, ...props }, ref) => {
    const { sheetId } = useSheetContext();
    return (
      <p
        ref={ref}
        id={`sheet-desc-${sheetId}`}
        className={cn('text-sm text-[var(--cf-fg-muted)] leading-relaxed', className)}
        {...props}
      />
    );
  }
);
SheetDescription.displayName = 'SheetDescription';

export interface SheetFooterProps extends React.HTMLAttributes<HTMLDivElement> {}

export const SheetFooter = React.forwardRef<HTMLDivElement, SheetFooterProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4 border-t border-[var(--cf-border)]', className)}
      {...props}
    />
  )
);
SheetFooter.displayName = 'SheetFooter';

export interface SheetCloseProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}

export const SheetClose = React.forwardRef<HTMLButtonElement, SheetCloseProps>(
  ({ onClick, children, className, ...props }, ref) => {
    const { onOpenChange } = useSheetContext();

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      onOpenChange(false);
      onClick?.(e);
    };

    return (
      <button
        ref={ref}
        type="button"
        onClick={handleClick}
        className={className}
        {...props}
      >
        {children}
      </button>
    );
  }
);
SheetClose.displayName = 'SheetClose';

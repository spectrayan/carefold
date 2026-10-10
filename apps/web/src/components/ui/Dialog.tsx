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

interface DialogContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dialogId: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const DialogContext = React.createContext<DialogContextValue | null>(null);

function useDialogContext() {
  const context = React.useContext(DialogContext);
  if (!context) {
    throw new Error('Dialog compound components must be rendered within a <Dialog>');
  }
  return context;
}

export interface DialogProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function Dialog({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children
}: DialogProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const dialogId = React.useId();

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
    <DialogContext.Provider
      value={{
        open: isOpen,
        onOpenChange: handleOpenChange,
        dialogId,
        triggerRef
      }}
    >
      {children}
    </DialogContext.Provider>
  );
}

export interface DialogTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const DialogTrigger = React.forwardRef<HTMLButtonElement, DialogTriggerProps>(
  ({ children, onClick, className, ...props }, ref) => {
    const { open, onOpenChange, triggerRef } = useDialogContext();

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
DialogTrigger.displayName = 'DialogTrigger';

export interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const sizeStyles: Record<'sm' | 'md' | 'lg' | 'xl', string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl'
};

export const DialogContent = React.forwardRef<HTMLDivElement, DialogContentProps>(
  ({ size = 'md', className, children, ...props }, ref) => {
    const { open, onOpenChange, dialogId, triggerRef } = useDialogContext();
    const contentRef = React.useRef<HTMLDivElement | null>(null);
    const prevActiveElementRef = React.useRef<HTMLElement | null>(null);

    // Save previous active element & handle focus trap
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

    return (
      <div
        className="fixed inset-0 z-[var(--cf-z-modal)] flex items-center justify-center p-4"
        role="presentation"
      >
        {/* Backdrop Scrim */}
        <div
          className="fixed inset-0 bg-[var(--cf-overlay)] backdrop-blur-sm transition-opacity"
          aria-hidden="true"
          onClick={() => onOpenChange(false)}
        />

        {/* Dialog Surface */}
        <div
          ref={(el) => {
            contentRef.current = el;
            if (typeof ref === 'function') ref(el);
            else if (ref) ref.current = el;
          }}
          role="dialog"
          aria-modal="true"
          aria-labelledby={`dialog-title-${dialogId}`}
          aria-describedby={`dialog-desc-${dialogId}`}
          tabIndex={-1}
          className={cn(
            'relative w-full rounded-[var(--cf-radius-xl)] bg-[var(--cf-surface)] p-6 shadow-3 border border-[var(--cf-border)]',
            'focus:outline-none transition-all',
            sizeStyles[size],
            className
          )}
          {...props}
        >
          {children}
        </div>
      </div>
    );
  }
);
DialogContent.displayName = 'DialogContent';

export interface DialogHeaderProps extends React.HTMLAttributes<HTMLDivElement> {}

export const DialogHeader = React.forwardRef<HTMLDivElement, DialogHeaderProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col space-y-1.5 pb-4 text-left', className)}
      {...props}
    />
  )
);
DialogHeader.displayName = 'DialogHeader';

export interface DialogTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  as?: 'h1' | 'h2' | 'h3' | 'h4';
}

export const DialogTitle = React.forwardRef<HTMLHeadingElement, DialogTitleProps>(
  ({ as: Component = 'h2', className, ...props }, ref) => {
    const { dialogId } = useDialogContext();
    return (
      <Component
        ref={ref}
        id={`dialog-title-${dialogId}`}
        className={cn('text-lg font-semibold leading-none tracking-tight text-[var(--cf-fg)]', className)}
        {...props}
      />
    );
  }
);
DialogTitle.displayName = 'DialogTitle';

export interface DialogDescriptionProps extends React.HTMLAttributes<HTMLParagraphElement> {}

export const DialogDescription = React.forwardRef<HTMLParagraphElement, DialogDescriptionProps>(
  ({ className, ...props }, ref) => {
    const { dialogId } = useDialogContext();
    return (
      <p
        ref={ref}
        id={`dialog-desc-${dialogId}`}
        className={cn('text-sm text-[var(--cf-fg-muted)] leading-relaxed', className)}
        {...props}
      />
    );
  }
);
DialogDescription.displayName = 'DialogDescription';

export interface DialogFooterProps extends React.HTMLAttributes<HTMLDivElement> {}

export const DialogFooter = React.forwardRef<HTMLDivElement, DialogFooterProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4 border-t border-[var(--cf-border)]', className)}
      {...props}
    />
  )
);
DialogFooter.displayName = 'DialogFooter';

export interface DialogCloseProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}

export const DialogClose = React.forwardRef<HTMLButtonElement, DialogCloseProps>(
  ({ onClick, children, className, ...props }, ref) => {
    const { onOpenChange } = useDialogContext();

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
DialogClose.displayName = 'DialogClose';

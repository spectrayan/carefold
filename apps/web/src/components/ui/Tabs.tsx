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

interface TabsContextValue {
  value: string;
  onValueChange: (value: string) => void;
  orientation: 'horizontal' | 'vertical';
  activationMode: 'automatic' | 'manual';
  tabIds: string[];
  registerTab: (id: string) => void;
  unregisterTab: (id: string) => void;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabsContext() {
  const context = React.useContext(TabsContext);
  if (!context) {
    throw new Error('Tabs compound components must be rendered within a <Tabs> container');
  }
  return context;
}

export interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  orientation?: 'horizontal' | 'vertical';
  activationMode?: 'automatic' | 'manual';
}

export const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  (
    {
      value: controlledValue,
      defaultValue,
      onValueChange,
      orientation = 'horizontal',
      activationMode = 'automatic',
      children,
      className,
      ...props
    },
    ref
  ) => {
    const [uncontrolledValue, setUncontrolledValue] = React.useState<string>(defaultValue || '');
    const isControlled = controlledValue !== undefined;
    const activeValue = isControlled ? controlledValue : uncontrolledValue;
    const [tabIds, setTabIds] = React.useState<string[]>([]);

    const handleValueChange = React.useCallback(
      (val: string) => {
        if (!isControlled) {
          setUncontrolledValue(val);
        }
        onValueChange?.(val);
      },
      [isControlled, onValueChange]
    );

    const registerTab = React.useCallback((id: string) => {
      setTabIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
    }, []);

    const unregisterTab = React.useCallback((id: string) => {
      setTabIds((prev) => prev.filter((i) => i !== id));
    }, []);

    // Set first registered tab if uncontrolled and value is empty
    React.useEffect(() => {
      if (!isControlled && !uncontrolledValue && tabIds.length > 0) {
        setUncontrolledValue(tabIds[0]);
      }
    }, [isControlled, uncontrolledValue, tabIds]);

    return (
      <TabsContext.Provider
        value={{
          value: activeValue,
          onValueChange: handleValueChange,
          orientation,
          activationMode,
          tabIds,
          registerTab,
          unregisterTab
        }}
      >
        <div
          ref={ref}
          className={cn(
            orientation === 'vertical' ? 'flex flex-row space-x-4' : 'flex flex-col space-y-3',
            className
          )}
          {...props}
        >
          {children}
        </div>
      </TabsContext.Provider>
    );
  }
);
Tabs.displayName = 'Tabs';

export interface TabsListProps extends React.HTMLAttributes<HTMLDivElement> {
  'aria-label'?: string;
}

export const TabsList = React.forwardRef<HTMLDivElement, TabsListProps>(
  ({ className, 'aria-label': ariaLabel, children, ...props }, ref) => {
    const { orientation, tabIds, value, onValueChange, activationMode } = useTabsContext();

    const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (tabIds.length === 0) return;

      const currentIndex = tabIds.indexOf(value);
      let targetIndex = currentIndex;

      const isHorizontal = orientation === 'horizontal';
      const prevKey = isHorizontal ? 'ArrowLeft' : 'ArrowUp';
      const nextKey = isHorizontal ? 'ArrowRight' : 'ArrowDown';

      if (e.key === nextKey) {
        e.preventDefault();
        targetIndex = (currentIndex + 1) % tabIds.length;
      } else if (e.key === prevKey) {
        e.preventDefault();
        targetIndex = (currentIndex - 1 + tabIds.length) % tabIds.length;
      } else if (e.key === 'Home') {
        e.preventDefault();
        targetIndex = 0;
      } else if (e.key === 'End') {
        e.preventDefault();
        targetIndex = tabIds.length - 1;
      } else {
        return;
      }

      const targetValue = tabIds[targetIndex];
      const targetElement = document.getElementById(`tab-${targetValue}`);
      targetElement?.focus();

      if (activationMode === 'automatic') {
        onValueChange(targetValue);
      }
    };

    return (
      <div
        ref={ref}
        role="tablist"
        aria-orientation={orientation}
        aria-label={ariaLabel}
        onKeyDown={handleKeyDown}
        className={cn(
          'inline-flex items-center rounded-[var(--cf-radius-lg)] p-1 bg-[var(--cf-surface-2)] border border-[var(--cf-border)]',
          orientation === 'vertical' ? 'flex-col space-y-1' : 'flex-row space-x-1',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
TabsList.displayName = 'TabsList';

export interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
  badge?: string | number;
}

export const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ value: tabValue, badge, children, className, onClick, onKeyDown, ...props }, ref) => {
    const { value: activeValue, onValueChange, registerTab, unregisterTab, activationMode } =
      useTabsContext();
    const isSelected = activeValue === tabValue;

    React.useEffect(() => {
      registerTab(tabValue);
      return () => unregisterTab(tabValue);
    }, [tabValue, registerTab, unregisterTab]);

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      onValueChange(tabValue);
      onClick?.(e);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (activationMode === 'manual' && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        onValueChange(tabValue);
      }
      onKeyDown?.(e);
    };

    return (
      <button
        ref={ref}
        id={`tab-${tabValue}`}
        role="tab"
        type="button"
        aria-selected={isSelected}
        aria-controls={`panel-${tabValue}`}
        tabIndex={isSelected ? 0 : -1}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        className={cn(
          'inline-flex items-center justify-center font-medium text-sm transition-all select-none',
          'min-h-[44px] px-3.5 py-1.5 rounded-[var(--cf-radius-md)] relative',
          'focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] focus-visible:outline-offset-2',
          isSelected
            ? 'bg-[var(--cf-surface)] text-[var(--cf-fg)] shadow-1 font-semibold'
            : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)]',
          className
        )}
        {...props}
      >
        <span>{children}</span>
        {badge !== undefined && (
          <span
            className={cn(
              'ml-2 px-1.5 py-0.5 text-xs rounded-full leading-none font-semibold',
              isSelected
                ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)]'
                : 'bg-[var(--cf-surface-3)] text-[var(--cf-fg-subtle)]'
            )}
          >
            {badge}
          </span>
        )}
      </button>
    );
  }
);
TabsTrigger.displayName = 'TabsTrigger';

export interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
}

export const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ value: tabValue, children, className, ...props }, ref) => {
    const { value: activeValue } = useTabsContext();
    const isSelected = activeValue === tabValue;

    if (!isSelected) {
      return null;
    }

    return (
      <div
        ref={ref}
        id={`panel-${tabValue}`}
        role="tabpanel"
        aria-labelledby={`tab-${tabValue}`}
        tabIndex={0}
        className={cn(
          'focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] focus-visible:outline-offset-2',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
TabsContent.displayName = 'TabsContent';

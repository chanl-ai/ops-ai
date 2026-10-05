import type React from 'react';
import type { ReactNode } from 'react';
import { createElement, isValidElement } from 'react';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import Link from 'next/link';
import { Icon } from '@/components/icon';
import type { LucideIcon } from 'lucide-react';
import { ArrowLeft, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  BulkSelectionContext,
  useBulkSelectionProvider,
} from '@/components/bulk-selection-context';

interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageLayoutProps {
  // Icon - flexible rendering support (Lucide icons recommended)
  icon?: LucideIcon | React.ComponentType<{ className?: string }> | ReactNode;

  // Content hierarchy
  title: string | ReactNode;
  description?: string | ReactNode;

  // Actions area
  actions?: ReactNode;
  actionsLoading?: boolean;

  // Layout control
  contentClassName?: string;
  headerClassName?: string;

  // Feature flags
  showBreadcrumbs?: boolean;
  breadcrumbs?: Breadcrumb[];

  // Metadata
  badge?: ReactNode;
  tabs?: ReactNode;

  // Navigation
  backHref?: string;

  // Interaction
  onTitleClick?: () => void;

  // Main content
  children: ReactNode;

  // Outer wrapper override — use className="px-0 py-0" when nested inside a
  // section layout that already provides its own outer padding (e.g. settings).
  className?: string;
}

export function PageLayout({
  icon,
  title,
  description,
  actions,
  actionsLoading,
  contentClassName,
  headerClassName,
  showBreadcrumbs,
  breadcrumbs,
  badge,
  tabs,
  backHref,
  onTitleClick,
  children,
  className,
}: PageLayoutProps) {
  const { bulkState, ctxValue } = useBulkSelectionProvider();

  const renderIcon = () => {
    if (!icon) return null;

    // If it's already a valid React element, return as-is
    if (isValidElement(icon)) {
      return icon;
    }

    // If it's a Lucide icon (function component), use our Icon component
    if (typeof icon === 'function') {
      return <Icon icon={icon as LucideIcon} size="lg" />;
    }

    // If it's a component with $$typeof (React component type)
    if (typeof icon === 'object' && icon !== null && '$$typeof' in icon) {
      return createElement(icon as unknown as React.ComponentType<{ className?: string }>, {
        className: 'h-6 w-6',
      });
    }

    // Otherwise, render as-is
    return icon;
  };

  // Bulk selection UI replaces normal actions when rows are selected
  const renderActions = () => {
    if (actionsLoading) {
      return (
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-9 w-24" />
        </div>
      );
    }

    if (bulkState) {
      return (
        <div className="flex items-center gap-2" data-testid="bulk-selection-bar">
          <Badge
            variant="secondary"
            className="h-8 px-3 rounded-md font-normal"
            data-testid="selected-count-badge"
          >
            {bulkState.count} selected
          </Badge>
          {bulkState.actions.map((action, i) => {
            const ActionIcon = action.icon;
            return (
              <Button
                key={i}
                variant={action.variant || 'outline'}
                size="sm"
                className="h-8"
                onClick={action.onClick}
                data-testid={`bulk-action-${action.label.toLowerCase().replace(/\s+/g, '-')}`}
              >
                {ActionIcon && <ActionIcon className="mr-2 h-4 w-4" />}
                {action.label}
              </Button>
            );
          })}
          <Button
            variant="ghost"
            size="sm"
            className="h-8"
            onClick={bulkState.onClear}
            data-testid="clear-selection-button"
          >
            Clear
            <X className="ml-1 h-4 w-4" />
          </Button>
        </div>
      );
    }

    return actions ? <div className="flex items-center gap-2">{actions}</div> : null;
  };

  return (
    <BulkSelectionContext.Provider value={ctxValue}>
      <div className={cn('flex flex-col h-full space-y-4 px-6 lg:px-8 py-6', className)}>
        {/* Breadcrumbs */}
        {showBreadcrumbs && breadcrumbs && breadcrumbs.length > 0 && (
          <nav className="flex items-center gap-2 text-sm text-muted-foreground">
            {breadcrumbs.map((crumb, i) => (
              <div key={i} className="flex items-center gap-2">
                {crumb.href ? (
                  <Link href={crumb.href} className="hover:text-foreground transition-colors">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="text-foreground">{crumb.label}</span>
                )}
                {i < breadcrumbs.length - 1 && <span className="text-muted-foreground">/</span>}
              </div>
            ))}
          </nav>
        )}

        {/* Header: wraps on narrow viewports; title truncates to avoid overflow */}
        <div
          className={cn(
            'flex flex-wrap items-center justify-between gap-x-4 gap-y-3 lg:flex-nowrap',
            headerClassName
          )}
          data-testid="page-header"
        >
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {icon &&
              (backHref ? (
                <Link
                  href={backHref}
                  aria-label="Back"
                  className="group relative flex h-14 w-14 shrink-0 items-center justify-center rounded-lg shadow-sm border text-muted-foreground bg-card transition-colors hover:border-primary/30 hover:text-primary"
                  data-testid="page-back-icon"
                >
                  <span className="transition-opacity duration-150 group-hover:opacity-0">
                    {renderIcon()}
                  </span>
                  <ArrowLeft className="absolute h-6 w-6 opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
                </Link>
              ) : (
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg shadow-sm border text-muted-foreground bg-card">
                  {renderIcon()}
                </div>
              ))}
            {/* Record pages without an icon (error and loading states) still need a way back. */}
            {!icon && backHref && (
              <Link
                href={backHref}
                aria-label="Back"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-card text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
                data-testid="page-back-icon"
              >
                <ArrowLeft className="h-4 w-4" />
              </Link>
            )}
            <div className="min-w-0 flex-1">
              {typeof title === 'string' ? (
                <h2
                  className={cn(
                    'text-xl font-semibold line-clamp-2 wrap-break-word sm:text-2xl',
                    onTitleClick && 'cursor-pointer hover:text-primary transition-colors'
                  )}
                  data-testid="page-title"
                  onClick={onTitleClick}
                  title={title}
                >
                  {title}
                </h2>
              ) : (
                <div
                  className="text-xl font-semibold min-w-0 wrap-break-word line-clamp-2 sm:text-2xl"
                  data-testid="page-title"
                >
                  {title}
                </div>
              )}
              {description && (
                <div
                  className="text-sm text-muted-foreground line-clamp-1 wrap-break-word mt-0.5"
                  title={typeof description === 'string' ? description : undefined}
                  data-testid="page-description"
                >
                  {description}
                </div>
              )}
              {badge && (
                <div
                  className="flex flex-wrap items-center gap-2 gap-y-1 mt-2"
                  data-testid="page-badges"
                >
                  {badge}
                </div>
              )}
            </div>
          </div>

          {/* Actions area — bulk selection overrides normal actions; wraps to own row on narrow */}
          <div className="flex items-center gap-2 shrink-0">{renderActions()}</div>
        </div>

        {/* Tabs (if provided) */}
        {tabs && <div className="pt-2">{tabs}</div>}

        {/* Content */}
        {/* px-1 / -mx-1 gives cards breathing room so borders & focus rings
            aren't clipped by the dashboard layout's overflow-x-hidden.
            No overflow here — the dashboard layout handles scrolling. */}
        <div className={cn('flex-1 px-1 -mx-1', contentClassName)}>{children}</div>
      </div>
    </BulkSelectionContext.Provider>
  );
}

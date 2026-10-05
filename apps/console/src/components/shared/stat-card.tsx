import { type LucideIcon, TrendingDown, TrendingUp } from 'lucide-react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/* ── StatCard ── */

const statCardVariants = cva(
  'rounded-xl border text-card-foreground shadow-xs @container/card',
  {
    variants: {
      variant: {
        default:
          'bg-gradient-to-t from-primary/5 to-card dark:bg-card dark:from-transparent',
        minimal: 'bg-card',
        compact: 'bg-card',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface StatCardProps extends VariantProps<typeof statCardVariants> {
  /** Primary label for the stat. Alias: `title` for migration compatibility. */
  label?: string;
  /** Alias for `label` — matches the old StatItem interface */
  title?: string;
  value: string | number | undefined;
  description?: string;
  icon?: LucideIcon;
  trend?: {
    value: string;
    direction: 'up' | 'down';
    isPositive?: boolean;
  };
  footer?: {
    text: string;
    subtext?: string;
  };
  className?: string;
  loading?: boolean;
}

export function StatCard({
  label,
  title,
  value,
  description,
  icon: Icon,
  trend,
  footer,
  variant = 'default',
  className,
  loading = false,
}: StatCardProps) {
  const resolvedLabel = label || title || '';
  const showSkeleton = loading || value === undefined;
  const TrendIcon = trend
    ? trend.direction === 'up'
      ? TrendingUp
      : TrendingDown
    : null;
  const isCompact = variant === 'compact';

  return (
    <div className={cn(statCardVariants({ variant }), className)}>
      {/* Header */}
      <div className="px-6 pt-6 pb-0">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm text-muted-foreground truncate">
            {description || resolvedLabel}
          </span>
          {Icon && (
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted/50 flex-shrink-0">
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
          )}
        </div>

        {/* Value */}
        {showSkeleton ? (
          <div className="mt-2 h-9 w-28 animate-pulse rounded-md bg-muted" />
        ) : (
          <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight @[250px]/card:text-3xl">
            {value}
          </div>
        )}

        {/* Trend badge */}
        {trend && !showSkeleton && (
          <div className="mt-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium">
            {TrendIcon && <TrendIcon className="h-3 w-3" />}
            {trend.value}
          </div>
        )}
      </div>

      {/* Footer — hidden for compact variant */}
      {!isCompact && footer && !showSkeleton && (
        <div className="flex flex-col gap-1.5 px-6 pb-6 pt-4 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            {footer.text}
            {TrendIcon && <TrendIcon className="h-4 w-4" />}
          </div>
          {footer.subtext && (
            <div className="text-muted-foreground">{footer.subtext}</div>
          )}
        </div>
      )}

      {/* Bottom padding when no footer */}
      {(isCompact || !footer || showSkeleton) && <div className="pb-6" />}
    </div>
  );
}

/* ── StatCardGrid ── */

export interface StatCardGridProps {
  children: React.ReactNode;
  columns?: 2 | 3 | 4;
  className?: string;
}

const columnMap = {
  2: 'grid grid-cols-1 sm:grid-cols-2 gap-4',
  3: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4',
  4: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4',
} as const;

export function StatCardGrid({
  children,
  columns = 4,
  className,
}: StatCardGridProps) {
  return (
    <div className={cn(columnMap[columns], className)}>
      {children}
    </div>
  );
}

export { statCardVariants };

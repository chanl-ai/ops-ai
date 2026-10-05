import { type LucideIcon, type LucideProps } from 'lucide-react';
import { cn } from '@/lib/utils';

interface IconProps extends Omit<LucideProps, 'size' | 'ref'> {
  icon: LucideIcon;
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'responsive';
  strokeWidth?: number;
  className?: string;
}

const sizeClasses = {
  xs: 'h-3 w-3',
  sm: 'h-4 w-4',
  md: 'h-5 w-5',
  lg: 'h-6 w-6',
  xl: 'h-8 w-8',
  responsive: 'h-7 w-7 md:h-10 md:w-10',
};

/**
 * Centralized icon component for Lucide icons with consistent styling
 *
 * @param icon - Lucide icon component to render
 * @param size - Predefined size variant (xs, sm, md, lg, xl, responsive)
 * @param strokeWidth - Icon stroke width (default: 2, min 1 for xs/sm/md sizes)
 * @param className - Additional classes to override or extend default styling
 * @param ...props - All other Lucide icon props (fill, color, absoluteStrokeWidth, etc.)
 *
 * @example
 * ```tsx
 * import { Sparkles } from "lucide-react"
 * import { Icon } from "@/components/icon"
 *
 * <Icon icon={Sparkles} size="lg" />
 * <Icon icon={Sparkles} size="responsive" /> // Smaller on mobile, larger on desktop
 * <Icon icon={Sparkles} size="md" className="text-primary" />
 * <Icon icon={Sparkles} size="lg" strokeWidth={1.5} /> // Thinner stroke
 * <Icon icon={Sparkles} size="xl" strokeWidth={3} /> // Bolder stroke
 * <Icon icon={Sparkles} fill="currentColor" /> // Filled icon
 * ```
 */
export function Icon({
  icon: LucideIcon,
  size = 'md',
  strokeWidth = 2,
  className,
  ...props
}: IconProps) {
  // Enforce minimum stroke width of 1 for smaller icons (xs, sm, md, responsive)
  // to maintain visibility and clarity
  const minStrokeForSmallIcons = ['xs', 'sm', 'md', 'responsive'].includes(size);
  const finalStrokeWidth = minStrokeForSmallIcons ? Math.max(1, strokeWidth) : strokeWidth;

  return (
    <LucideIcon
      className={cn(sizeClasses[size], 'text-foreground', className)}
      strokeWidth={finalStrokeWidth}
      {...props}
    />
  );
}

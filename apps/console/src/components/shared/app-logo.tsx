import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { initials } from '@/lib/format';
import { cn } from '@/lib/utils';

/** An app's logo, or its initials when it has none. One component for every place an app is shown by its mark. */
export function AppLogo({ name, logo, className, title }: { name: string; logo?: string | null; className?: string; title?: string }) {
  return (
    <Avatar className={cn('size-6 rounded-md', className)} title={title}>
      {logo && <AvatarImage src={logo} alt="" />}
      <AvatarFallback className="rounded-md text-[10px] font-semibold">{initials(name)}</AvatarFallback>
    </Avatar>
  );
}

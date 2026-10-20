import { Info } from 'lucide-react';

/** One-line explanation above an email configuration table. */
export function ConfigNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-sm text-muted-foreground">
      <Info className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

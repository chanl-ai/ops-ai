import { Button } from '@/components/ui/button';

/** Destructive and state-changing actions, kept at the end of a settings tab and separated by colour. */
export function DangerZone({ items }: { items: { title: string; description: string; action: string; onClick: () => void; destructive?: boolean; disabled?: boolean }[] }) {
  return (
    <div className="rounded-lg border border-destructive/30">
      <div className="border-b border-destructive/30 px-4 py-2.5 text-sm font-medium text-destructive">Danger zone</div>
      <ul className="divide-y">
        {items.map((i) => (
          <li key={i.title} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <div>
              <div className="text-sm font-medium">{i.title}</div>
              <div className="text-xs text-muted-foreground">{i.description}</div>
            </div>
            <Button variant={i.destructive ? 'destructive' : 'outline'} size="sm" onClick={i.onClick} disabled={i.disabled}>
              {i.action}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

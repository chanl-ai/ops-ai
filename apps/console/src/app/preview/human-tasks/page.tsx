'use client';

import { UserCheck } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import { LayoutA, LayoutB } from './_parts/frames';
import { useReviewQueue } from './_parts/use-review-queue';

/**
 * Design mock for the Human Tasks redesign (c-460): two layouts of one queue, chosen with ?layout=a or ?layout=b.
 * Deciding, the sign-in check, undo, reassigning and asking for more information all work on this page's own state.
 */
export default function HumanTasksPreview() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const layout = params.get('layout') === 'b' ? 'b' : 'a';
  const queue = useReviewQueue();
  const setLayout = (v: string) => {
    if (!v) return;
    const next = new URLSearchParams(params.toString());
    next.set('layout', v);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };
  return (
    <PageLayout
      icon={UserCheck}
      title="Human Tasks"
      description="Design mock: Harbor & Pine Bank sample data, soonest due first. Deciding changes this page only."
      className="min-h-0 flex-1 pb-0"
      contentClassName="flex min-h-0 flex-1 flex-col gap-3"
      actions={
        <ToggleGroup type="single" variant="outline" value={layout} onValueChange={setLayout} aria-label="Layout" data-testid="layout-switch">
          <ToggleGroupItem value="a" className="px-3" data-testid="layout-a-switch">
            A: Queue and task
          </ToggleGroupItem>
          <ToggleGroupItem value="b" className="px-3" data-testid="layout-b-switch">
            B: One at a time
          </ToggleGroupItem>
        </ToggleGroup>
      }
    >
      {layout === 'a' ? <LayoutA queue={queue} /> : <LayoutB queue={queue} />}
    </PageLayout>
  );
}

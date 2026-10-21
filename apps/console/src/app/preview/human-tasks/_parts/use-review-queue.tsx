'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { ME, QUEUE, type QueueItem, type Task } from '../_sample/data';

export interface Decision {
  option: string;
  reason: string;
  by: string;
}

/** Why an item left this person's queue without a decision. */
type Away = { kind: 'reassigned'; to: string } | { kind: 'info'; note: string };

const UNDO_MS = 10_000;

/**
 * The mock's queue, held in this page only: what is decided, what was handed on, which task is open (in the URL as
 * ?task=, so a reload or a link lands on it) and which row j and k have moved to. Deciding moves to the next task
 * straight away: the next undecided one in the same notice or case, then the next item by due time.
 */
export function useReviewQueue() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [decisions, setDecisions] = React.useState<Record<string, Decision>>({});
  const [away, setAway] = React.useState<Record<string, Away>>({});

  const items = React.useMemo(
    () => [...QUEUE].sort((a, b) => a.due.localeCompare(b.due)).filter((i) => !away[i.id] && i.tasks.some((t) => !decisions[t.id])),
    [decisions, away],
  );
  const decidedCount = Object.keys(decisions).length;
  const firstOpen = (item: QueueItem) => item.tasks.find((t) => !decisions[t.id]) ?? item.tasks[0];

  const taskParam = params.get('task');
  const located = React.useMemo(() => {
    for (const item of QUEUE) {
      const task = item.tasks.find((t) => t.id === taskParam);
      if (task) return { item, task };
    }
    return null;
  }, [taskParam]);
  const fallback = items[0] ? { item: items[0], task: firstOpen(items[0]) } : null;
  const active = located && !away[located.item.id] ? located : fallback;

  const open = React.useCallback(
    (taskId: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (taskId) next.set('task', taskId);
      else next.delete('task');
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  // The row j and k sit on; Enter opens it. It follows the open item until the keys move it.
  const [cursor, setCursor] = React.useState(0);
  const activeIndex = active ? items.findIndex((i) => i.id === active.item.id) : -1;
  React.useEffect(() => {
    if (activeIndex >= 0) setCursor(activeIndex);
  }, [activeIndex]);

  /** The task to show once `taskId` has left the queue: the rest of its item first, then the next item by due. */
  const nextAfter = (taskId: string, done: Record<string, Decision>, gone: Record<string, Away>): Task | null => {
    const sorted = [...QUEUE].sort((a, b) => a.due.localeCompare(b.due));
    const at = sorted.findIndex((i) => i.tasks.some((t) => t.id === taskId));
    const order = [...sorted.slice(at), ...sorted.slice(0, at)];
    for (const item of order) {
      if (gone[item.id]) continue;
      const t = item.tasks.find((x) => !done[x.id] && x.id !== taskId);
      if (t) return t;
    }
    return null;
  };

  const decide = (item: QueueItem, task: Task, option: string, reason: string) => {
    const chosen = task.options.find((o) => o.id === option)!;
    const done = { ...decisions, [task.id]: { option, reason, by: ME } };
    setDecisions(done);
    open(nextAfter(task.id, done, away)?.id ?? null);
    toast.success(chosen.outcome, {
      id: `decided-${task.id}`,
      // Top centre on every screen: at the foot it would sit over the next task's Decide.
      position: 'top-center',
      duration: UNDO_MS,
      description: (
        <span data-testid="decision-toast">
          {chosen.label} for {task.subject}, recorded with your name.{' '}
          <Link href={`/cases?search=${item.caseRef}`} className="font-medium underline underline-offset-2">
            Open case {item.caseRef}
          </Link>
        </span>
      ),
      action: {
        label: 'Undo',
        onClick: () => {
          setDecisions((d) => {
            const rest = { ...d };
            delete rest[task.id];
            return rest;
          });
          open(task.id);
        },
      },
    });
  };

  const handOn = (item: QueueItem, why: Away) => {
    const gone = { ...away, [item.id]: why };
    setAway(gone);
    open(nextAfter(item.tasks[0].id, decisions, gone)?.id ?? null);
    const title = why.kind === 'reassigned' ? `Reassigned to ${why.to}` : 'Asked for more information';
    toast.success(title, {
      position: 'top-center',
      duration: UNDO_MS,
      description: why.kind === 'reassigned' ? `${item.title} is in ${why.to}'s queue now.` : `${item.title} waits until the answer comes back to you.`,
      action: {
        label: 'Undo',
        onClick: () => {
          setAway((a) => {
            const rest = { ...a };
            delete rest[item.id];
            return rest;
          });
          open(firstOpen(item).id);
        },
      },
    });
  };

  return {
    items,
    active,
    decisions,
    decidedCount,
    cursor,
    setCursor,
    open,
    openItem: (item: QueueItem) => open(firstOpen(item).id),
    decide,
    reassign: (item: QueueItem, to: string) => handOn(item, { kind: 'reassigned', to }),
    askForInfo: (item: QueueItem, note: string) => handOn(item, { kind: 'info', note }),
  };
}

export type ReviewQueue = ReturnType<typeof useReviewQueue>;

/**
 * j and k move through the queue, Enter opens the row they are on. Keys typed into a field, or with a modifier held,
 * are left alone.
 */
export function useQueueKeys(queue: ReviewQueue, onOpen?: () => void) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest('[role="dialog"],[role="menu"]'))) return;
      const n = queue.items.length;
      if (!n) return;
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault();
        queue.setCursor((c) => Math.min(n - 1, Math.max(0, c + (e.key === 'j' ? 1 : -1))));
      } else if (e.key === 'Enter' && !t?.closest('button,a,[role="radio"],[role="tab"]')) {
        const item = queue.items[Math.min(queue.cursor, n - 1)];
        if (!item) return;
        e.preventDefault();
        queue.openItem(item);
        onOpen?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [queue, onOpen]);
}

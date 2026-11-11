'use client';

import * as React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Briefcase, ChevronDown, Database, Hammer, ShieldCheck, type LucideIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuShortcut, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useMyPermissions, useNavAllows, useWorkspaceIdentity } from '@/hooks/me-queries';
import { areaOf, type AreaName, firstPageOf, offeredAreas, rowsOfArea } from '@/lib/nav';

const ICONS: Record<AreaName, LucideIcon> = { Work: Briefcase, Build: Hammer, Data: Database, Govern: ShieldCheck };

// What the person last did in the sidebar, kept in this browser under their own address so a second person on the same
// browser starts from Work. The area is the last one shown; pages is the last page visited in each area.
const KEY = 'ops.sidebar.area';
interface Memory {
  area?: AreaName;
  pages: Partial<Record<AreaName, string>>;
}

function readMemory(person?: string): Memory {
  if (!person) return { pages: {} };
  try {
    const saved = JSON.parse(window.localStorage.getItem(`${KEY}.${person}`) ?? '{}');
    return { area: typeof saved?.area === 'string' ? saved.area : undefined, pages: saved?.pages && typeof saved.pages === 'object' ? saved.pages : {} };
  } catch {
    // No storage, or a value this version cannot read: the person starts from Work.
    return { pages: {} };
  }
}

function writeMemory(person: string | undefined, memory: Memory) {
  if (!person) return;
  try {
    window.localStorage.setItem(`${KEY}.${person}`, JSON.stringify(memory));
  } catch {
    // Not remembered; the area still changes on this page.
  }
}

/**
 * The areas the person is offered and the one the sidebar shows. The page decides: a page of an area opens that area.
 * New chat has no area of its own to go by, so it shows the one the person last used. A page of an area the person is
 * not offered (a refused link) leaves the sidebar as it is and lights nothing.
 */
export function useAreas() {
  const pathname = usePathname();
  const router = useRouter();
  const allows = useNavAllows();
  const permissions = useMyPermissions();
  const person = useWorkspaceIdentity()?.user.email;
  const [, bump] = React.useReducer((n: number) => n + 1, 0);
  const ready = allows({ area: 'chat', action: 'run' }) !== undefined;
  const areas = ready ? offeredAreas(allows) : [];
  const memory = readMemory(person);
  const pathArea = areaOf(pathname);
  const here = pathArea && pathname !== '/chat' && areas.includes(pathArea) ? pathArea : null;
  const remembered = memory.area && areas.includes(memory.area) ? memory.area : undefined;
  const current: AreaName = here ?? remembered ?? areas[0] ?? 'Work';
  const lit = here ?? (pathArea === null || pathname === '/chat' ? current : null);

  // The Overview is for people with work to look at; a chat-only person who once had it in another team must not be sent back.
  const overview = rowsOfArea('Work', allows).some((i) => i.url === '/');
  const pageFor = (area: AreaName) => {
    const last = memory.pages[area];
    return last && areaOf(last) === area && (last !== '/' || overview) ? last : firstPageOf(area, allows);
  };
  const select = (area: AreaName) => {
    writeMemory(person, { ...memory, area });
    bump();
    router.push(pageFor(area));
  };
  return {
    areas,
    current,
    lit,
    ready,
    failed: !ready && permissions.isError,
    retry: () => void permissions.refetch(),
    select,
    // The effects below run in one place (AreaSwitcher); they read these.
    person,
    memory,
    pageFor,
    bump,
    overview,
  };
}

/** True while a field, a dialog or the search has the keyboard: a chord then belongs to it. */
function typing(e: KeyboardEvent): boolean {
  const target = e.target instanceof HTMLElement ? e.target : null;
  if (target?.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role=textbox]')) return true;
  return !!document.querySelector('[role=dialog], [role=alertdialog]');
}

/**
 * The area control in the top bar: four buttons beside the trail, one dropdown on a phone. Nothing is drawn for a person
 * with a single area, or while their cells load. ⌘1 to ⌘4 reach the offered areas in order; the page the person last
 * visited in an area is where it opens. It also keeps the memory and sends `/` to where the person left off.
 */
export function AreaSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const { areas, current, lit, ready, select, person, memory, pageFor, bump, overview } = useAreas();
  const router_ = React.useRef(router);
  router_.current = router;

  // Remember the page and its area. New chat has no area to go by and is not recorded.
  const here = areaOf(pathname);
  React.useEffect(() => {
    if (!person || !ready || !here || pathname === '/chat' || !areas.includes(here)) return;
    // The home page is about to send the person back to the area they left; recording Work here would erase it.
    if (pathname === '/' && memory.area && memory.area !== 'Work') return;
    if (memory.area === here && memory.pages[here] === pathname) return;
    writeMemory(person, { area: here, pages: { ...memory.pages, [here]: pathname } });
    bump();
  }, [person, ready, here, pathname, areas.join(), memory.area, memory.pages, bump]); // eslint-disable-line react-hooks/exhaustive-deps

  // The home page opens where the person left off; a person with no Overview (chat only) goes to their first page.
  React.useEffect(() => {
    if (pathname !== '/' || !person || !ready || !areas.length) return;
    const target = !overview ? areas[0] : memory.area && memory.area !== 'Work' && areas.includes(memory.area) ? memory.area : null;
    if (target) router_.current.replace(pageFor(target));
  }, [pathname, person, ready, areas.join()]); // eslint-disable-line react-hooks/exhaustive-deps

  React.useEffect(() => {
    if (areas.length < 2) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey) return;
      const n = Number(e.key);
      if (!Number.isInteger(n) || n < 1 || n > areas.length || typing(e)) return;
      e.preventDefault();
      select(areas[n - 1]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (areas.length < 2) return null;
  return (
    <>
      <ToggleGroup type="single" variant="outline" size="sm" value={lit ?? ''} onValueChange={(v) => v && v !== lit && select(v as AreaName)} role="group" aria-label="Area" className="shrink-0 max-md:hidden" data-testid="area-switcher">
        {areas.map((a) => {
          const Icon = ICONS[a];
          return (
            <ToggleGroupItem key={a} value={a} className="gap-1.5 px-2.5">
              <Icon />
              {a}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" className="h-11 shrink-0 gap-1.5 px-3 md:hidden" aria-label={`Area: ${current}. Switch area`}>
            {React.createElement(ICONS[current], { className: 'size-4' })}
            {current}
            <ChevronDown className="size-4 text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {areas.map((a, i) => {
            const Icon = ICONS[a];
            return (
              <DropdownMenuItem key={a} onSelect={() => select(a)} aria-current={a === lit ? 'true' : undefined}>
                <Icon className="size-4" />
                {a}
                <DropdownMenuShortcut>⌘{i + 1}</DropdownMenuShortcut>
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}

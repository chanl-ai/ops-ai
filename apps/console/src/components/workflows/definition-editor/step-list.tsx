'use client';

import * as React from 'react';
import { Plus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { EngineNodeType } from '@/lib/types/engine';
import { cn } from '@/lib/utils';

import { groupLook } from './definition-node';
import { paletteGroups } from './graph';

/** The tabs, in the order a builder reaches for them; a group the server adds later still shows under All. */
const TABS: { id: string; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'trigger', label: 'Triggers' },
  { id: 'ai', label: 'AI' },
  { id: 'human', label: 'People' },
  { id: 'action', label: 'Tools' },
  { id: 'flow', label: 'Flow' },
  { id: 'data', label: 'Data' },
];
const HEADING: Record<string, string> = Object.fromEntries(TABS.filter((t) => t.id !== 'all').map((t) => [t.id, t.label]));
const rank = (g: string) => {
  const i = TABS.findIndex((t) => t.id === g);
  return i < 0 ? TABS.length : i;
};

/**
 * "Add a step": a floating panel over the canvas with a tab per group of the server's step types and a search that
 * covers every group whichever tab is open. Picking a type hands it to `onAdd`, which places the step.
 */
export function StepList({ types, open, onOpenChange, onAdd, startTab = 'all' }: { types: EngineNodeType[]; open: boolean; onOpenChange: (open: boolean) => void; onAdd: (type: EngineNodeType) => void; startTab?: string }) {
  const [tab, setTab] = React.useState(startTab);
  const [query, setQuery] = React.useState('');
  const groups = React.useMemo(() => [...paletteGroups(types)].sort(([a], [b]) => rank(a) - rank(b)), [types]);
  const present = new Set(groups.map(([g]) => g));
  const tabs = TABS.filter((t) => t.id === 'all' || present.has(t.id));
  // A search looks in every group; without one the open tab picks the group.
  const shown = query.trim() || tab === 'all' ? groups : groups.filter(([g]) => g === tab);

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setQuery('');
      }}
    >
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="bg-card shadow-sm" data-testid="definition-add-step">
          <Plus /> <span className="max-sm:sr-only">Add a step</span>
          <Badge variant="outline" className="font-mono max-sm:hidden">
            N
          </Badge>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(30rem,calc(100vw-3rem))] overflow-hidden p-0" data-testid="step-list">
        <Tabs value={tab} onValueChange={setTab} orientation="vertical" className="flex-row gap-0">
          <TabsList aria-label="Step groups" className="h-auto w-28 shrink-0 flex-col items-stretch justify-start gap-0.5 rounded-none border-r p-1.5">
            {tabs.map((t) => (
              <TabsTrigger key={t.id} value={t.id} className="h-8 flex-none justify-start px-2.5" data-testid={`step-tab-${t.id}`}>
                {t.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <Command className="min-w-0 flex-1 rounded-none">
            <CommandInput placeholder="Search every step" value={query} onValueChange={setQuery} />
            <CommandList className="max-h-[min(24rem,55vh)]">
              <CommandEmpty>No step matches.</CommandEmpty>
              {shown.map(([group, list]) => (
                <CommandGroup key={group} heading={HEADING[group] ?? group} data-testid="definition-palette-group">
                  {list.map((t) => {
                    const look = groupLook(t.group, t.id);
                    const Icon = look.icon;
                    return (
                      <CommandItem key={t.id} value={`${t.label} ${t.description} ${t.id}`} onSelect={() => onAdd(t)} className="items-start gap-2.5 py-2" data-type={t.id}>
                        <span className={cn('mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md', look.tile)}>
                          <Icon className="size-3.5" aria-hidden />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium">{t.label}</span>
                          <span className="line-clamp-2 text-xs text-muted-foreground">{t.description}</span>
                        </span>
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </Tabs>
      </PopoverContent>
    </Popover>
  );
}

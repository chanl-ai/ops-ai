'use client';

import type { ReactNode } from 'react';
import { MoreHorizontal } from 'lucide-react';

import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@/components/ui/item';
import { initials } from '@/lib/format';

export interface EntityAction {
  label: string;
  onClick: () => void;
  destructive?: boolean;
}

/** A member, key or host: an avatar or icon, a name, a line of meta, optional trailing content and a dots menu. */
export function EntityRow({ name, meta, icon, avatar, trailing, actions }: { name: string; meta?: ReactNode; icon?: ReactNode; avatar?: boolean; trailing?: ReactNode; actions?: EntityAction[] }) {
  const plain = actions?.filter((a) => !a.destructive) ?? [];
  const danger = actions?.filter((a) => a.destructive) ?? [];
  return (
    <Item variant="outline" size="sm" className="bg-card" data-testid="entity-row">
      <ItemMedia variant={avatar ? 'default' : 'icon'}>
        {avatar ? (
          <Avatar className="size-8">
            <AvatarFallback className="text-xs">{initials(name)}</AvatarFallback>
          </Avatar>
        ) : (
          icon
        )}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>{name}</ItemTitle>
        {meta && <ItemDescription>{meta}</ItemDescription>}
      </ItemContent>
      <ItemActions>
        {trailing}
        {actions?.length ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Actions for ${name}`}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {plain.map((a) => (
                <DropdownMenuItem key={a.label} onSelect={a.onClick}>
                  {a.label}
                </DropdownMenuItem>
              ))}
              {plain.length > 0 && danger.length > 0 && <DropdownMenuSeparator />}
              {danger.map((a) => (
                <DropdownMenuItem key={a.label} variant="destructive" onSelect={a.onClick}>
                  {a.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </ItemActions>
    </Item>
  );
}

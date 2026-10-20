'use client';

import type { ReactNode } from 'react';
import { Lock } from 'lucide-react';

import { SettingCard } from '@/components/shared/setting/setting-card';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { initials } from '@/lib/format';

/** A card whose control is a picture on the right (a workspace logo), with "optional but recommended" in the footer. */
export function ImageSettingCard({ title, description, name, children, onSave }: { title: string; description: string; name: string; children?: ReactNode; onSave?: () => void }) {
  return (
    <SettingCard
      title={title}
      description={description}
      aside={
        <Avatar className="size-14 rounded-lg">
          <AvatarFallback className="rounded-lg text-lg">{initials(name)}</AvatarFallback>
        </Avatar>
      }
      help="Optional but recommended. A square image of at least 128 pixels."
      onSave={onSave}
      saveLabel="Upload"
    >
      {children}
    </SettingCard>
  );
}

/** A feature behind a role or plan: the footer names what it needs and offers the action that gets it. */
export function GatedCard({ title, description, needs, price, action, onAction }: { title: string; description: string; needs: string; price?: string; action: string; onAction: () => void }) {
  return (
    <SettingCard
      title={title}
      description={description}
      help={
        <span className="inline-flex items-center gap-1.5">
          <Lock className="size-3.5" /> Needs {needs}
          {price ? ` · ${price}` : ''}
        </span>
      }
      footerEnd={
        <Button type="button" size="sm" onClick={onAction}>
          {action}
        </Button>
      }
    />
  );
}

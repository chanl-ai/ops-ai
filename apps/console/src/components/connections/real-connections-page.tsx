'use client';

import * as React from 'react';
import { type SystemCard } from '@/hooks/systems-queries';

import { ConnectSystemDialog, type ConnectMode, type ConnectTarget } from './connect-system-dialog';
import { SystemsGrid } from './systems-grid';

/** What a card's Connect opens the dialog on: the card's connection, its module with none yet, or a new system. */
function targetOf(system: SystemCard | null): ConnectTarget | null {
  if (!system) return { kind: 'new' };
  if (system.connectionId) return { kind: 'connection', connectionId: system.connectionId };
  if (system.kind === 'plugin' && system.plugin) return { kind: 'plugin', card: system };
  if (system.kind === 'module' && system.moduleIds[0]) return { kind: 'module', moduleId: system.moduleIds[0], name: system.name };
  return null;
}

/** The real-connections Connections page (c-580): the systems grid, and the one connect dialog it opens. */
export function RealConnectionsPage() {
  const [open, setOpen] = React.useState<{ target: ConnectTarget; mode: ConnectMode; key: number } | null>(null);
  const show = (system: SystemCard | null, mode: ConnectMode) => {
    const target = targetOf(system);
    if (target) setOpen({ target, mode, key: Date.now() });
  };
  return (
    <>
      <SystemsGrid onConnect={(s, mode) => show(s, mode)} onNew={() => show(null, 'connect')} />
      {open && <ConnectSystemDialog key={open.key} target={open.target} mode={open.mode} open onOpenChange={(o) => !o && setOpen(null)} />}
    </>
  );
}

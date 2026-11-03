'use client';

import * as React from 'react';
import { useSearchParams } from 'next/navigation';
import { type SystemCard, useConnectionKinds } from '@/hooks/systems-queries';
import type { Kinds } from '@/lib/connect-plan';

import { ConnectWindow, connectsInWindow } from './connect-window';
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

/**
 * The apps catalog. A plugin that signs in with an account connects in the Connect window, through Ops AI's app or the
 * team's own; a key, a password or a custom app opens the connect dialog with its fields.
 */
export function RealConnectionsPage() {
  const kinds = useConnectionKinds();
  const [open, setOpen] = React.useState<{ target: ConnectTarget; mode: ConnectMode; key: number } | null>(null);
  const [windowFor, setWindowFor] = React.useState<SystemCard | null>(null);
  // A link from a tool's app picker (`?new=1`) opens Add custom app here, the one place an app is added.
  const asked = useSearchParams().get('new') === '1';
  React.useEffect(() => {
    if (asked) setOpen({ target: { kind: 'new' }, mode: 'connect', key: Date.now() });
  }, [asked]);
  const show = (system: SystemCard | null, mode: ConnectMode) => {
    if (system && mode === 'connect' && connectsInWindow(system, kinds.data as Kinds | undefined)) return setWindowFor(system);
    const target = targetOf(system);
    if (target) setOpen({ target, mode, key: Date.now() });
  };
  return (
    <>
      <SystemsGrid onConnect={(s, mode) => show(s, mode)} onNew={() => show(null, 'connect')} />
      {windowFor && kinds.data && <ConnectWindow card={windowFor} kinds={kinds.data as Kinds} open onOpenChange={(o) => !o && setWindowFor(null)} />}
      {open && <ConnectSystemDialog key={open.key} target={open.target} mode={open.mode} open onOpenChange={(o) => !o && setOpen(null)} />}
    </>
  );
}

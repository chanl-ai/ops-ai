'use client';

import * as React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { onSessionEnded, setDeployment, setSession } from '@/lib/api';

import { EmbedChat } from './embed-chat';

const PREFIX = 'ops-chat:';
// The iframe can load before the loader listens, so it says ready until it is identified.
const READY_EVERY_MS = 300;

/** The person the session names, read from its claims for the footer and greeting; the server checks the session. */
function personOf(session: string): { name: string } | null {
  try {
    const part = session.split('.')[1];
    const claims = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))) as { name?: string; email?: string };
    return { name: claims.name || claims.email || 'you' };
  } catch {
    return null;
  }
}

/** The page that framed this one, when the deployment lists it; messages go to that origin and no other. */
function parentOrigin(allowed: string[]): string | null {
  const ancestors = (window.location as Location & { ancestorOrigins?: DOMStringList }).ancestorOrigins;
  const candidate = ancestors?.length ? ancestors[0] : document.referrer ? new URL(document.referrer).origin : null;
  return candidate && allowed.includes(candidate) ? candidate : null;
}

export interface FrameProps {
  deployment: string;
  agentName: string;
  suggestions: string[];
  allowedOrigins: string[];
}

/**
 * The chat inside the loader's iframe (c-158). It takes messages only from its parent window at the origin the
 * deployment lists, and posts only there: ready (repeated until identified), identified, session-ended on a 401,
 * sign-in, closed, and message with the role and time only. The transcript never leaves this frame.
 */
export function Frame({ deployment, agentName, suggestions, allowedOrigins }: FrameProps) {
  const [client] = React.useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const [origin, setOrigin] = React.useState<string | null>(null);
  const [person, setPerson] = React.useState<{ name: string } | null | undefined>(undefined);
  const [canSignIn, setCanSignIn] = React.useState(false);
  const [threadId, setThreadId] = React.useState<string>();
  const storageKey = `ops-chat:${deployment}:thread`;

  setDeployment(deployment);

  const post = React.useCallback(
    (type: string, data: Record<string, unknown> = {}) => {
      if (origin) window.parent.postMessage({ type: PREFIX + type, ...data }, origin);
    },
    [origin],
  );

  React.useEffect(() => {
    setOrigin(parentOrigin(allowedOrigins));
    try {
      setThreadId(sessionStorage.getItem(storageKey) ?? undefined);
    } catch {
      // Storage can be blocked in a third-party frame; the chat then starts fresh each load.
    }
  }, [allowedOrigins, storageKey]);

  React.useEffect(() => {
    if (!origin) return;
    const onMessage = (e: MessageEvent) => {
      if (e.source !== window.parent || e.origin !== origin) return;
      const data = e.data as { type?: unknown; session?: unknown; signIn?: unknown };
      if (data?.type !== `${PREFIX}identify`) return;
      const session = typeof data.session === 'string' && data.session ? data.session : null;
      setSession(session);
      setCanSignIn(data.signIn === true);
      setPerson(session ? personOf(session) : null);
      if (session) post('identified');
      else post('signed-out');
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [origin, post]);

  React.useEffect(() => {
    if (!origin || person !== undefined) return;
    post('ready');
    const timer = window.setInterval(() => post('ready'), READY_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [origin, person, post]);

  React.useEffect(() => onSessionEnded(() => post('session-ended')), [post]);

  const chooseThread = React.useCallback(
    (id: string | undefined) => {
      setThreadId(id);
      try {
        if (id) sessionStorage.setItem(storageKey, id);
        else sessionStorage.removeItem(storageKey);
      } catch {
        // See above.
      }
    },
    [storageKey],
  );
  const onMessageRole = React.useCallback((role: 'user' | 'assistant') => post('message', { role, at: new Date().toISOString() }), [post]);

  if (!origin) return <p className="p-4 text-sm text-muted-foreground" data-testid="embed-unframed">This chat opens from a page the bank has set it up on.</p>;
  if (person === undefined) return null;
  return (
    <QueryClientProvider client={client}>
      <EmbedChat
        agentName={agentName}
        suggestions={suggestions}
        person={person}
        canSignIn={canSignIn}
        threadId={threadId}
        onThread={chooseThread}
        onSignIn={() => post('sign-in')}
        onClose={() => post('closed')}
        onMessage={onMessageRole}
      />
    </QueryClientProvider>
  );
}

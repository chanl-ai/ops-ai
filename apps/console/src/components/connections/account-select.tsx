'use client';

import * as React from 'react';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAppAccounts, useSystems } from '@/hooks/systems-queries';

const NONE = '__none__';

/**
 * Which of an app's team accounts a step or an agent uses (app id to account name): the app, then its account, with Default first.
 * Only the team's live accounts are listed (a step's run may act for nobody); the publish check confirms the name.
 */
export function AccountSelect({ id, value, onChange }: { id: string; value: Record<string, unknown>; onChange: (v: Record<string, string>) => void }) {
  const apps = useSystems();
  const plugins = (apps.data ?? []).filter((c) => c.kind === 'plugin' && c.appGroup !== 'gone');
  const [app, setApp] = React.useState<string>(Object.keys(value)[0] ?? '');
  const accounts = useAppAccounts(app || undefined);
  // A package app (one that runs inside another, such as a loan package in a Salesforce org) has no accounts: the API
  // lists the accounts of the app it runs on, under that app's id, which is the key the step names the account by.
  const key = accounts.data?.[0]?.appId ?? app;
  const appName = plugins.find((c) => c.id === app)?.name ?? 'This app';
  const named = typeof value[key] === 'string' ? (value[key] as string) : '';
  const fallback = (accounts.data ?? []).find((a) => a.default);
  return (
    <div className="flex flex-col gap-2 sm:flex-row" data-field={id}>
      <Select value={app || NONE} onValueChange={(v) => (setApp(v === NONE ? '' : v), onChange({}))}>
        <SelectTrigger className="w-full sm:w-1/2" aria-label="App" data-testid={`${id}-app`}>
          <SelectValue placeholder={apps.isPending ? 'Loading…' : 'Choose an app'} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Each app’s default</SelectItem>
          {plugins.map((c) => (
            <SelectItem key={c.id} value={c.id}>
              {c.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {app && (
        <Select value={named || NONE} onValueChange={(v) => onChange(v === NONE ? {} : { [key]: v })}>
          <SelectTrigger id={id} className="w-full sm:w-1/2" aria-busy={accounts.isFetching || undefined} data-testid={`${id}-account`}>
            <SelectValue placeholder={accounts.isPending ? 'Loading…' : 'Choose'} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>
              {fallback ? `Default (${fallback.name}${(fallback.missingObjects ?? []).length > 0 ? `, ${appName} not installed` : ''})` : 'Default'}
            </SelectItem>
            {(accounts.data ?? [])
              .filter((a) => !a.default)
              .map((a) => (
                <SelectItem key={a.id} value={a.name} disabled={(a.missingObjects ?? []).length > 0} data-testid={`${id}-account-${a.name}`}>
                  <span className="truncate">{a.name}</span>
                  <span className="ml-2 truncate text-xs text-muted-foreground">
                    {(a.missingObjects ?? []).length > 0 ? `${appName} not installed` : (a.identity ?? []).map((e) => e.shown).join(' · ')}
                  </span>
                </SelectItem>
              ))}
            {named && !(accounts.data ?? []).some((a) => a.name === named) && <SelectItem value={named}>{`${named} · not one of the team’s accounts`}</SelectItem>}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

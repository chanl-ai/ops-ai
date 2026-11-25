'use client';

import * as React from 'react';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SearchSelect } from '@/components/shared/search-select';
import { teamAppOptions } from '@/hooks/options-queries';
import { useAppAccounts, useSystemCard } from '@/hooks/systems-queries';

const NONE = '__none__';

/**
 * Which of an app's team accounts a step or an agent uses (app id to account name): the app, then its account, with Default first.
 * Only the team's live accounts are listed (a step's run may act for nobody); the publish check confirms the name.
 * `withTestAccounts` also lists the app's test account, marked, for a try, which runs on whichever account is picked.
 */
export function AccountSelect({ id, value, onChange, withTestAccounts = false }: { id: string; value: Record<string, unknown>; onChange: (v: Record<string, string>) => void; withTestAccounts?: boolean }) {
  const [app, setApp] = React.useState<string>(Object.keys(value)[0] ?? '');
  const chosen = useSystemCard(app || undefined);
  const accounts = useAppAccounts(app || undefined, { withTest: withTestAccounts });
  // A package app (one that runs inside another, such as a loan package in a Salesforce org) has no accounts: the API
  // lists the accounts of the app it runs on, under that app's id, which is the key the step names the account by.
  const key = accounts.data?.[0]?.appId ?? app;
  const appName = chosen.data?.name ?? 'This app';
  const named = typeof value[key] === 'string' ? (value[key] as string) : '';
  const fallback = (accounts.data ?? []).find((a) => a.default);
  return (
    <div className="flex flex-col gap-2 sm:flex-row" data-field={id}>
      <SearchSelect
        source={teamAppOptions}
        value={app ? { id: app, label: appName } : null}
        onChange={(id) => (setApp(id), onChange({}))}
        placeholder="Each app’s default"
        noneLabel="Each app’s default"
        searchPlaceholder="Search apps"
        emptyText="No app matches."
        ariaLabel="App"
        className="w-full sm:w-1/2"
        testId={`${id}-app`}
      />
      {app && (
        <Select value={named || NONE} onValueChange={(v) => onChange(v === NONE ? {} : { [key]: v })}>
          <SelectTrigger id={id} className="w-full sm:w-1/2" aria-busy={accounts.isFetching || undefined} data-testid={`${id}-account`}>
            {accounts.isError && !named ? (
              <span className="text-destructive-text" data-testid={`${id}-account-error`}>{`Couldn’t load ${appName}’s accounts`}</span>
            ) : (
              <SelectValue placeholder={accounts.isPending ? 'Loading…' : 'Choose'} />
            )}
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
                    {(a.missingObjects ?? []).length > 0 ? `${appName} not installed` : a.sandbox ? 'Test account' : (a.identity ?? []).map((e) => e.shown).join(' · ')}
                  </span>
                </SelectItem>
              ))}
            {named && !(accounts.data ?? []).some((a) => a.name === named) && <SelectItem value={named}>{`${named} · not an account of this team`}</SelectItem>}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

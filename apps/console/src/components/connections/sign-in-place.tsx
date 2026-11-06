'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { SystemCard } from '@/hooks/systems-queries';

type PluginSetting = NonNullable<NonNullable<SystemCard['plugin']>['settings']>[number];
// A plugin's setting, or the same field as an auth config's answer describes it: what the control reads of either.
type Setting = Pick<PluginSetting, 'label'> & {
  perAccount?: boolean;
  locked?: boolean;
  choices?: { value: string | number | boolean; label: string; hint?: string | null; testAccount?: boolean | null }[] | null;
  other?: { label: string; value: string; hosts: string[]; hint?: string | null; placeholder?: string | null; testAccountHosts?: string[] | null } | null;
};

// The Select's value for "your company's address", which is no choice of the plugin's.
const OTHER = '__other__';

/** A setting that asks where an account signs in: one with the plugin's choices or a typed company host. One asked on
 * the auth config is asked of an account only when its config leaves it unset (connect-window.tsx). */
export const isSignInPlace = (s: PluginSetting) => s.perAccount && !s.locked && s.asked !== 'settings' && Boolean(s.choices?.length || s.other);

/** Whether `value` is a place test accounts sign in at: a choice marked so, or a typed host under a test host. */
export function isTestPlace(setting: Setting, value: string): boolean {
  if ((setting.choices ?? []).some((c) => c.testAccount && String(c.value) === value)) return true;
  const host = hostOf(setting, value);
  return Boolean(host && (setting.other?.testAccountHosts ?? []).some((h) => host.endsWith(h)));
}

/** The host a typed company address holds, when `value` is the setting's `other` address with a host in it. */
function hostOf(setting: Setting, value: string): string | null {
  const template = setting.other?.value;
  if (!template || !template.includes('{host}')) return null;
  const [head, tail] = template.split('{host}');
  if (!value.startsWith(head) || !value.endsWith(tail)) return null;
  return value.slice(head.length, value.length - tail.length) || null;
}

/**
 * Where an account signs in, in the system's words (Salesforce's "Where do you sign in to Salesforce?"): the plugin's
 * choices, or the company's own address typed as its host. `value` is the setting's full value, as the API takes it.
 */
export function SignInPlace({ setting, value, onChange, testId }: { setting: Setting; value: string; onChange: (value: string) => void; testId: string }) {
  const choices = setting.choices ?? [];
  const chosen = choices.find((c) => String(c.value) === value);
  const typed = chosen ? null : hostOf(setting, value);
  const [other, setOther] = React.useState(!chosen && (typed !== null || !choices.length));
  // A value set from outside (another account starting from the first's address) shows as what it is.
  React.useEffect(() => {
    if (typed !== null) setOther(true);
    else if (chosen) setOther(false);
  }, [typed, chosen]);
  const host = typed ?? '';
  const pick = (v: string) => {
    if (v === OTHER) {
      setOther(true);
      onChange(setting.other?.value.replace('{host}', host) ?? '');
      return;
    }
    setOther(false);
    onChange(v);
  };
  return (
    <FormField id={testId} label={setting.label} hint={other ? setting.other?.hint || undefined : choices.find((c) => String(c.value) === value)?.hint || undefined}>
      <div className="flex flex-col gap-2">
        <Select value={other ? OTHER : chosen ? String(chosen.value) : ''} onValueChange={pick}>
          <SelectTrigger id={testId} className="w-full" data-testid={testId}>
            <SelectValue placeholder="Choose where it signs in" />
          </SelectTrigger>
          <SelectContent>
            {choices.map((c) => (
              <SelectItem key={String(c.value)} value={String(c.value)} data-testid={`${testId}-${String(c.label)}`}>
                {c.hint ? `${c.label} · ${c.hint}` : c.label}
              </SelectItem>
            ))}
            {setting.other && (
              <SelectItem value={OTHER} data-testid={`${testId}-other`}>
                {setting.other.label}
              </SelectItem>
            )}
          </SelectContent>
        </Select>
        {other && setting.other && (
          <Input
            value={host}
            onChange={(e) => onChange(setting.other?.value.replace('{host}', e.target.value.trim()) ?? '')}
            placeholder={setting.other.placeholder ?? undefined}
            aria-label={setting.other.label}
            data-testid={`${testId}-host`}
          />
        )}
      </div>
    </FormField>
  );
}

/** How an auth config holds a sign-in value: every account's (fixed), or where each Connect starts (default). */
export type ConfigMode = 'default' | 'fixed';

export const MODE_LABEL: Record<ConfigMode, string> = { fixed: 'Fixed', default: 'Default' };

/** Whether accounts on the config all sign in at its value, or start there and may pick another in Connect. */
export function ConfigModeSelect({ value, onChange, testId }: { value: ConfigMode; onChange: (mode: ConfigMode) => void; testId: string }) {
  return (
    <FormField id={testId} label="Accounts on this config" hint={value === 'fixed' ? 'Every account signs in here.' : 'Connect starts here, and an account may sign in elsewhere.'}>
      <Select value={value} onValueChange={(v) => onChange(v as ConfigMode)}>
        <SelectTrigger id={testId} className="w-full" data-testid={testId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="fixed" data-testid={`${testId}-fixed`}>
            Always sign in here
          </SelectItem>
          <SelectItem value="default" data-testid={`${testId}-default`}>
            Start here, may change
          </SelectItem>
        </SelectContent>
      </Select>
    </FormField>
  );
}

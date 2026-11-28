'use client';

import * as React from 'react';

import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { FormField } from '@/components/shared/form-field';
import { QueryError } from '@/components/shared/query-states';
import { SearchSelect } from '@/components/shared/search-select';
import { fixedOptions } from '@/hooks/options-queries';
import { SampleData } from '@/components/shared/sample-data';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Section } from '@/components/shared/surface';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useCanSetDefaultAgent, useChatAgents, useDefaultAgent } from '@/hooks/chat-queries';
import { useTeam } from '@/hooks/use-team';

const OWNERS = fixedOptions('team-owners', [
  { id: 'ops', label: 'Operations leads' },
  { id: 'platform', label: 'Platform admins' },
]);
const OWNER_LABEL: Record<string, string> = { ops: 'Operations leads', platform: 'Platform admins' };

/**
 * Team › General. The default agent is stored (agents-service `/v1/chat/default-agent`); the team's name and
 * owner have no service yet, so those cards are sample data and say so.
 */
export default function GeneralSettingsPage() {
  const { team } = useTeam();
  const [name, setName] = React.useState('');
  const [owner, setOwner] = React.useState<string | null>('ops');
  React.useEffect(() => {
    if (team) setName(team.name);
  }, [team]);
  const current = useDefaultAgent();
  const agents = useChatAgents();
  const isAdmin = useCanSetDefaultAgent();
  const [picked, setPicked] = React.useState<{ id: string; name: string }>();
  const value = current.data?.agentId;
  const gone = !!value && !current.data?.agentName;

  return (
    <SettingsPageLayout sample={false} section="General" description="Choices that apply to everyone in this team.">
      <Section title="Default agent" description="New chats start on this agent. It answers itself or asks the team's other agents, and anyone can switch to a specialist with @.">
        {current.isPending || agents.isPending ? (
          <Skeleton className="h-9 w-72" />
        ) : current.isError || agents.isError ? (
          <QueryError what="the default agent" onRetry={() => (current.refetch(), agents.refetch())} error={current.error ?? agents.error} retrying={current.isFetching || agents.isFetching} />
        ) : (
          <FormField
            id="default-agent"
            label="Agent"
            hint={
              !isAdmin
                ? 'A team admin changes this.'
                : gone
                  ? 'The default is no longer live, so new chats ask people to pick an agent until you choose another.'
                  : !value
                    ? 'No default yet: new chats ask people to pick an agent.'
                    : undefined
            }
          >
            <Select value={value && !gone ? value : undefined} disabled={!isAdmin} onValueChange={(id) => id && setPicked(agents.data.find((a) => a.id === id))}>
              <SelectTrigger id="default-agent" className="w-full sm:w-72" data-testid="default-agent-select">
                <SelectValue placeholder="Choose an agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.data.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
      </Section>
      <SampleData>
        <SettingCard id="name" title="Team name" description="Shown in the team switcher and on everything the team owns." help="Please use 32 characters at maximum." onSave={() => undefined}>
          <Input value={name} maxLength={32} onChange={(e) => setName(e.target.value)} aria-label="Team name" className="w-full bg-card sm:w-1/2" />
        </SettingCard>
        <SettingCard id="owner" title="Owner" description="The group that answers for what this team runs." onSave={() => undefined}>
          <div className="w-full sm:w-1/2">
            <SearchSelect source={OWNERS} value={owner ? { id: owner, label: OWNER_LABEL[owner] ?? owner } : null} onChange={setOwner} placeholder="Pick a group" searchPlaceholder="Search groups…" ariaLabel="Owner" className="w-full" />
          </div>
        </SettingCard>
      </SampleData>
      <MakeDefaultAgentDialog agent={picked} open={!!picked} onOpenChange={(o) => !o && setPicked(undefined)} />
    </SettingsPageLayout>
  );
}

'use client';

import * as React from 'react';

import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { FormField } from '@/components/shared/form-field';
import { QueryError } from '@/components/shared/query-states';
import { Combobox } from '@/components/shared/setting/pickers';
import { SampleData } from '@/components/shared/sample-data';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Section } from '@/components/shared/surface';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useCanSetDefaultAgent, useChatAgents, useDefaultAgent } from '@/hooks/chat-queries';
import { useTeam } from '@/hooks/use-team';

const OWNERS = [
  { value: 'ops', label: 'Operations leads' },
  { value: 'platform', label: 'Platform admins' },
];

/**
 * Team › General. The default agent is stored (agents-service `/v1/chat/default-agent`, c-174); the team's name and
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
    <SettingsPageLayout section="General" description="Choices that apply to everyone in this team.">
      <SampleData>
        <SettingCard id="name" title="Team name" description="Shown in the team switcher and on everything the team owns." help="Please use 32 characters at maximum." onSave={() => undefined}>
          <Input value={name} maxLength={32} onChange={(e) => setName(e.target.value)} aria-label="Team name" className="w-full bg-card sm:w-1/2" />
        </SettingCard>
        <SettingCard id="owner" title="Owner" description="The group that answers for what this team runs." onSave={() => undefined}>
          <div className="w-full sm:w-1/2">
            <Combobox options={OWNERS} value={owner} onChange={setOwner} noun="groups" />
          </div>
        </SettingCard>
      </SampleData>
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
            <Select value={value && !gone ? value : undefined} disabled={!isAdmin} onValueChange={(id) => setPicked(agents.data.find((a) => a.id === id))}>
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
      <MakeDefaultAgentDialog agent={picked} open={!!picked} onOpenChange={(o) => !o && setPicked(undefined)} />
    </SettingsPageLayout>
  );
}

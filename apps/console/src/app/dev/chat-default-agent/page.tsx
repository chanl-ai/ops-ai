'use client';

import * as React from 'react';
import { notFound } from 'next/navigation';
import { ArrowLeft, AtSign, Bot } from 'lucide-react';

import { AssistantMessage, UserMessage } from '@/components/chat/message-view';
import { PageLayout } from '@/components/page-layout';
import { FormField } from '@/components/shared/form-field';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import type { ChatMessage } from '@/lib/types/chat';

import { AGENTS, DEFAULT_THREAD, HANDED_OVER, type TeamAgent } from './sample';

/**
 * The c-174 preview: chat starts on the team's default agent, which calls specialist agents as tools (agent__<id>, as
 * workflows are called); typing @ hands the chat to an agent until Back. General settings picks the default. Mock data,
 * dev server only, not in the nav; nothing here calls a service.
 */
export default function ChatDefaultAgentPreview() {
  if (process.env.NODE_ENV !== 'development') notFound();
  return <Preview />;
}

function Preview() {
  const [defaultId, setDefaultId] = React.useState(AGENTS[0].id);
  const [talkingTo, setTalkingTo] = React.useState<TeamAgent | null>(null);
  const [messages, setMessages] = React.useState<ChatMessage[]>(DEFAULT_THREAD);
  const fallback = AGENTS.find((a) => a.id === defaultId) ?? AGENTS[0];
  const current = talkingTo ?? fallback;

  const handOver = (agent: TeamAgent) => {
    setTalkingTo(agent);
    if (agent.id === 'ag_fraud') setMessages([...DEFAULT_THREAD, ...HANDED_OVER]);
  };

  return (
    <PageLayout title="Chat (c-174 preview)" description="One assistant per team that asks a specialist when it needs one">
      <Tabs defaultValue="chat" className="gap-4">
        <TabsList>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="settings">General settings</TabsTrigger>
        </TabsList>
        <TabsContent value="chat" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2" data-testid="chat-agent">
            <Bot className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">{current.name}</span>
            {!talkingTo && <Badge variant="secondary">Team default</Badge>}
          </div>
          {talkingTo && (
            <Alert data-testid="handover-banner">
              <AtSign className="size-4" />
              <AlertTitle>You are talking to {talkingTo.name}</AlertTitle>
              <AlertDescription className="flex flex-wrap items-center gap-3">
                It answers you directly. {fallback.name} picks up again when you go back.
                <Button size="sm" variant="outline" onClick={() => setTalkingTo(null)} data-testid="handover-back">
                  <ArrowLeft /> Back to {fallback.name}
                </Button>
              </AlertDescription>
            </Alert>
          )}
          <Section flush bodyClassName="flex flex-col gap-4 p-4">
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserMessage key={m.id} message={m} />
              ) : (
                <AssistantMessage key={m.id} message={m} onOpenDocument={() => undefined} onCopy={() => undefined} />
              ),
            )}
          </Section>
          <MentionComposer agents={AGENTS.filter((a) => a.id !== current.id)} placeholder={`Message ${current.name}, or type @ to ask another agent…`} onMention={handOver} />
        </TabsContent>
        <TabsContent value="settings">
          <Section title="Team default agent" description="Chat starts here. It calls the team's other published agents as tools when a question needs them.">
            <FormField id="default-agent" label="Default agent" hint="A new workspace gets its first agent from provisioning; it stays the default until someone changes it here.">
              <Select value={defaultId} onValueChange={setDefaultId}>
                <SelectTrigger id="default-agent" className="w-full sm:w-80" data-testid="default-agent-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {AGENTS.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </Section>
        </TabsContent>
      </Tabs>
    </PageLayout>
  );
}

/** The composer with @ mentions: typing @ lists the team's other agents; choosing one hands the chat to it. */
function MentionComposer({ agents, placeholder, onMention }: { agents: TeamAgent[]; placeholder: string; onMention: (agent: TeamAgent) => void }) {
  const [text, setText] = React.useState('');
  const open = /(^|\s)@\w*$/.test(text);
  return (
    <Popover open={open}>
      <PopoverAnchor asChild>
        <div>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} rows={3} aria-label="Message" data-testid="mention-composer" />
        </div>
      </PopoverAnchor>
      <PopoverContent align="start" className="w-80 p-0" onOpenAutoFocus={(e) => e.preventDefault()}>
        <Command>
          <CommandInput placeholder="Ask an agent…" />
          <CommandList>
            <CommandEmpty>No agent by that name.</CommandEmpty>
            <CommandGroup heading="Your team's agents">
              {agents.map((a) => (
                <CommandItem
                  key={a.id}
                  value={a.name}
                  onSelect={() => {
                    onMention(a);
                    setText('');
                  }}
                  data-testid={`mention-${a.id}`}
                >
                  <div className="flex flex-col">
                    <span className="font-medium">{a.name}</span>
                    <span className="text-xs text-muted-foreground">{a.role}</span>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

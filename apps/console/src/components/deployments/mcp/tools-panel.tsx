'use client';

import Link from 'next/link';

import { EmptyState } from '@/components/shared/empty-state';
import { RiskBadge } from '@/components/status-badges';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { count, plural } from '@/lib/format';
import { WORKFLOW_TOOL_APPROVAL } from '@/components/agents/workflow-tool-facts';
import type { ConnectAudience, ConnectTool } from '@/lib/types/connect';
import { Route } from 'lucide-react';


/**
 * The workflows assistants and agents can call, ranked. One switch per audience: Assistants creates, resumes or
 * pauses the workflow's MCP deployment; Agents registers it as a workflow tool agents can be granted. The two are
 * independent, and neither changes the workflow's gates.
 */
export function ToolsPanel({ tools, workflowCount, exposedCount, pendingId, onToggle }: { tools: ConnectTool[]; workflowCount: number; exposedCount: number; pendingId: string | null; onToggle: (t: ConnectTool, audience: ConnectAudience, exposed: boolean) => void }) {
  return (
    <Card className="gap-3" data-testid="connect-tools">
      <CardHeader>
        <CardTitle>What assistants and agents can call</CardTitle>
        <CardDescription>
          {exposedCount} of {workflowCount} workflows exposed. Assistants call them over the MCP URL; agents call them as a tool once granted. Each runs with the caller&apos;s own access and keeps its review gates.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {tools.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-6">Workflow</TableHead>
                <TableHead>Risk tier</TableHead>
                <TableHead>When called</TableHead>
                <TableHead className="text-right">Calls</TableHead>
                <TableHead className="text-right">Assistants</TableHead>
                <TableHead className="pr-6 text-right">Agents</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tools.map((t) => {
                const sw = (audience: ConnectAudience) => {
                  const on = t.exposedTo.includes(audience);
                  // An agent grant pins the tool; withdrawing it from agents waits until no agent holds it.
                  const held = audience === 'agents' && on && t.grantedAgents > 0;
                  const control = (
                    <Switch
                      checked={on}
                      disabled={!!t.disabledReason || held || pendingId === t.workflowId}
                      onCheckedChange={(v) => onToggle(t, audience, v)}
                      aria-label={`Expose ${t.name} to ${audience}`}
                      data-testid={`expose-${audience}-${t.workflowId}`}
                    />
                  );
                  if (t.disabledReason)
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="inline-flex flex-col items-end gap-1">
                            {control}
                            <span className="text-xs text-muted-foreground" data-testid={`expose-reason-${audience}-${t.workflowId}`}>
                              Not published
                            </span>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>{t.disabledReason}</TooltipContent>
                      </Tooltip>
                    );
                  if (held)
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="inline-flex flex-col items-end gap-1">
                            {control}
                            <span className="text-xs text-muted-foreground">{plural(t.grantedAgents, 'agent')}</span>
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>Granted to {plural(t.grantedAgents, 'agent')}. Revoke the grants before withdrawing it from agents.</TooltipContent>
                      </Tooltip>
                    );
                  return control;
                };
                return (
                  <TableRow key={t.workflowId} data-testid={`tool-row-${t.workflowId}`}>
                    <TableCell className="pl-6">
                      <Link href={`/workflows/${t.workflowId}`} className="font-medium hover:underline">
                        {t.name}
                      </Link>
                      <div className="font-mono text-xs text-muted-foreground">{t.toolId}</div>
                    </TableCell>
                    <TableCell>
                      <RiskBadge risk={t.tier} />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{WORKFLOW_TOOL_APPROVAL[t.approval]}</TableCell>
                    <TableCell className="text-right tabular-nums">{count(t.calls)}</TableCell>
                    <TableCell className="text-right">{sw('assistants')}</TableCell>
                    <TableCell className="pr-6 text-right">{sw('agents')}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : (
          <EmptyState icon={Route} title="No published workflows yet" description="Publish a workflow, then expose it here so assistants can call it." action={{ label: 'Open workflows', href: '/workflows' }} />
        )}
      </CardContent>
      <CardFooter className="justify-between gap-2 text-sm">
        <Link href="/workflows" className="underline underline-offset-2">
          View all {workflowCount} workflows →
        </Link>
        <Link href="/deployments" className="text-muted-foreground underline underline-offset-2">
          Manage deployments →
        </Link>
      </CardFooter>
    </Card>
  );
}

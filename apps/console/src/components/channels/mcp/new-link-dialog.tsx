'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { Wrench } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';

import { DialogShell } from '@/components/shared/dialog-shell';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCreateMcpLink } from '@/hooks/mcp-link-queries';
import { linkToolOptions, useOptionLabels } from '@/hooks/options-queries';
import { useTeam } from '@/hooks/use-team';
import type { ToolOptionsPage } from '@/lib/types/query';

// tools-service takes at most 20 tools on a link; past that an assistant reads a list too long to choose from.
const MAX_TOOLS = 20;

const schema = z.object({
  name: z.string().trim().min(1, 'Name the link.').max(120, 'Keep the name under 120 characters.'),
  tools: z.array(z.string()).min(1, 'Pick at least one tool.').max(MAX_TOOLS, `A link offers at most ${MAX_TOOLS} tools.`),
});
type Values = z.infer<typeof schema>;

/**
 * Makes a link in the team the person is working in: a name, the environment and the tools, searched on the server from
 * what the team may run (the agent page's tools picker, which lists the team's grantable tools and published
 * workflows). A write always waits for a person when an assistant calls it.
 */
export function NewLinkDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const { team } = useTeam();
  const create = useCreateMcpLink();
  const form = useForm<Values>({ resolver: zodResolver(schema), mode: 'onBlur', defaultValues: { name: '', tools: [] } });
  const picked = form.watch('tools');
  const labels = useOptionLabels(linkToolOptions, picked);
  React.useEffect(() => {
    if (open) form.reset({ name: '', tools: [] });
  }, [open, form]);

  const submit = form.handleSubmit((v) => {
    // The labels query reads the link picker's own source, whose options carry these fields.
    const option = new Map(((labels.data?.data ?? []) as ToolOptionsPage['data']).map((o) => [o.id, o]));
    create.mutate(
      // A workflow carries what it takes and does, as the picker read it, so assistants see its inputs.
      { name: v.name.trim(), tools: v.tools.map((id) => ({ id, label: option.get(id)?.label ?? id, inputSchema: option.get(id)?.inputSchema ?? null, description: option.get(id)?.description ?? null })) },
      {
        onSuccess: (link) => {
          toast.success(`Made ${link.name}`, { description: 'Copy its address into an assistant to connect.' });
          onOpenChange(false);
          router.push(`/build/channels/mcp/${encodeURIComponent(link.id)}`);
        },
        onError: (e) => form.setError('root', { message: e.message }),
      },
    );
  });

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New MCP link"
      description="One address for a set of this team’s tools. People connect their assistant to it with their own sign-in."
      onSubmit={submit}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={create.isPending} loadingText="Creating…" data-testid="mcp-link-create">
            Create link
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4" data-testid="mcp-new-link">
        <FormField id="mcp-link-name" label="Name" hint="People see this name in their assistant." error={form.formState.errors.name?.message}>
          <Input id="mcp-link-name" placeholder="e.g. Claims lookups" {...form.register('name')} aria-invalid={!!form.formState.errors.name} data-testid="mcp-link-name" />
        </FormField>
        <FormField id="mcp-link-team" label="Team" hint="A link belongs to the team you are working in. Switch team at the top to make one in another.">
          <Input id="mcp-link-team" value={team?.name ?? ''} readOnly disabled />
        </FormField>
        <FormField id="mcp-link-env" label="Environment" hint="Production is off for outside assistants on this install.">
          <Select value="test">
            <SelectTrigger id="mcp-link-env" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="test">Test</SelectItem>
              <DisabledReason reason="Outside assistants reach test data until an admin turns production on for the install.">
                <SelectItem value="production" disabled>
                  Production
                </SelectItem>
              </DisabledReason>
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="mcp-link-tools" label="Tools" hint="Writes always wait for a person to approve." error={form.formState.errors.tools?.message}>
          <Controller
            control={form.control}
            name="tools"
            render={({ field }) => (
              <EntityPicker
                source={linkToolOptions}
                value={field.value}
                onChange={(ids) => field.onChange(ids)}
                addLabel="Pick tools"
                searchPlaceholder="Search tools by name or system…"
                emptyText="No tool matches. Install the app first, or search by another name."
                icon={Wrench}
                testId="mcp-link-tools"
              />
            )}
          />
        </FormField>
        {form.formState.errors.root?.message && (
          <p className="text-sm text-destructive" role="alert" data-testid="mcp-link-error">
            {form.formState.errors.root.message}
          </p>
        )}
      </div>
    </DialogShell>
  );
}

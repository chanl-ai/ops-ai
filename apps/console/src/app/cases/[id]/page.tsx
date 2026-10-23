'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { CheckCircle2, ChevronDown, Clock, FileText, Link2, ListChecks, Mail, PlayCircle, SlidersHorizontal } from 'lucide-react';
import { toast } from 'sonner';

import { CASE_PRIORITY, CASE_STATUS, Deadline, PRIORITY_OPTIONS, STATUS_OPTIONS } from '@/components/cases/case-record-columns';
import { CaseFields } from '@/components/cases/case-fields';
import { PageLayout } from '@/components/page-layout';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { CopyIconButton } from '@/components/shared/setting/copy-field';
import { MiddleTruncate } from '@/components/shared/setting/middle-truncate';
import { AttributeCard, RecordLayout } from '@/components/shared/record-layout';
import { Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item';
import { Textarea } from '@/components/ui/textarea';
import { StoryFeed } from '@/components/workflows/story-feed';
import { useAddCaseNote, useCaseRecord, useChangeCaseRecord } from '@/hooks/case-record-queries';
import { useMe } from '@/hooks/me-queries';
import { relativeTime } from '@/lib/format';
import type { CaseClock, CasePriority, CaseRecordDetail, CaseRecordPatch, CaseStatus } from '@/lib/types/case-records';

const ACTION_KIND: Record<string, string> = { reply: 'Reply', tool: 'Tool call' };
const ACTION_STATUS: Record<string, string> = { pending: 'Waiting on its task', approved: 'Approved', refused: 'Refused', rejected: 'Rejected' };

/** A clock from the server's state: met and paused say so; a running or breached one counts down or up. */
function ClockState({ clock, paused, testId }: { clock: CaseClock; paused: boolean; testId: string }) {
  return <Deadline left={clock.leftS} at={clock.dueAt} paused={paused || clock.state === 'paused'} met={clock.state === 'met'} testId={testId} />;
}

/** A capped list's "all" link, when the server gives one. */
const AllLink = ({ href, label }: { href: string | null | undefined; label: string }) =>
  href ? (
    <Link href={href} className="text-xs font-medium text-primary underline-offset-4 hover:underline">
      {label}
    </Link>
  ) : null;

/**
 * One case (GET /v1/cases/{id}, c-291 assembled, c-292 page): what it is about, what it waits on, what is drafted and
 * what is next. Every value, label and link comes from the response, so a new case type needs no console change.
 */
export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const query = useCaseRecord(id);
  const change = useChangeCaseRecord();
  const note = useAddCaseNote();
  const me = useMe().data?.user.email;
  const [noteOpen, setNoteOpen] = React.useState(false);
  const [text, setText] = React.useState('');

  if (query.isPending)
    return (
      <PageLayout icon={Mail} title="Case" backHref="/cases">
        <PageSkeleton statCards={0} tableRows={6} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout icon={Mail} title="Case" backHref="/cases">
        <QueryError what="this case" error={query.error} onRetry={() => query.refetch()} retrying={query.isFetching} />
      </PageLayout>
    );
  const c: CaseRecordDetail = query.data;
  // A service without c-291's keys still answers; the server enforces each write either way.
  const may = c.permissions ?? { assign: true, changeStatus: true, close: true, note: true };
  const owner = c.owner?.name ?? c.assignee ?? 'Unassigned';
  const customer = c.customer?.name ?? c.customerName ?? c.customerId;
  const paused = !!(c.sla?.pausedSince ?? c.pausedSince);
  const fields = c.typedFields ?? [];
  const left = c.whatsLeft;
  const resolve = () => save({ status: 'resolved' }, 'The case is resolved');
  const actions = c.actions ?? [];
  const links = c.links;

  const save = async (patch: CaseRecordPatch, done: string) => {
    try {
      await change.mutateAsync({ id: c.id, patch });
      toast.success(done);
    } catch (e) {
      toast.error('Couldn’t change the case', { description: (e as Error).message });
    }
  };
  const addNote = async () => {
    try {
      await note.mutateAsync({ id: c.id, text: text.trim() });
      setText('');
      setNoteOpen(false);
      toast.success('Note added');
    } catch (e) {
      toast.error('Couldn’t add the note', { description: (e as Error).message });
    }
  };

  return (
    <PageLayout
      icon={Mail}
      title={c.subject}
      description={[customer ?? 'No customer', c.team ? `team ${c.team.name}` : null, `owner ${owner}`].filter(Boolean).join(' · ')}
      backHref="/cases"
      badge={
        <>
          <Badge variant="secondary" data-testid="case-status-badge">
            {CASE_STATUS[c.status]}
          </Badge>
          <Badge variant="outline" className="font-normal" data-testid="case-priority-badge">
            {CASE_PRIORITY[c.priority]}
          </Badge>
          {/* One timer (c-500): the case type's deadline field, else the resolution clock; first response stays in Details. */}
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="case-timer">
            {c.timer?.label ?? 'Resolution'}{' '}
            <ClockState
              clock={
                c.timer
                  ? { state: c.timer.state, dueAt: c.timer.dueAt, leftS: c.timer.leftS, metAt: null }
                  : (c.sla?.resolution ?? { state: 'running', dueAt: c.resolutionDueAt, leftS: c.resolutionLeftS, metAt: null })
              }
              paused={c.timer ? c.timer.state === 'paused' : paused}
              testId="case-resolution"
            />
          </span>
        </>
      }
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {may.assign && me && c.assignee !== me && (
            <Button variant="outline" disabled={change.isPending} onClick={() => save({ assignee: me }, 'The case is yours')} data-testid="case-take">
              Assign to me
            </Button>
          )}
          {may.changeStatus && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" disabled={change.isPending} data-testid="case-change-status">
                  Change status
                  <ChevronDown className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Status</DropdownMenuLabel>
                {STATUS_OPTIONS.filter((o) => may.close || o.value !== 'closed' || o.value === c.status).map((o) => (
                  <DropdownMenuItem
                    key={o.value}
                    disabled={o.value === c.status}
                    onSelect={() => save({ status: o.value as CaseStatus }, `Status is ${o.label}`)}
                    data-testid={`case-status-${o.value}`}
                  >
                    {o.label}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuLabel className="text-xs text-muted-foreground">Priority</DropdownMenuLabel>
                {PRIORITY_OPTIONS.map((o) => (
                  <DropdownMenuItem
                    key={o.value}
                    disabled={o.value === c.priority}
                    onSelect={() => save({ priority: o.value as CasePriority }, `Priority is ${o.label}`)}
                    data-testid={`case-priority-${o.value}`}
                  >
                    {o.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {may.note && (
            <Button onClick={() => setNoteOpen(true)} data-testid="case-add-note-open">
              Add note
            </Button>
          )}
        </div>
      }
    >
      <RecordLayout
        rail={
          <>
            {links && (
              <AttributeCard title="Linked records" icon={Link2} testId="case-links">
                {/* Each kind of link has its row, so an empty one says None rather than vanishing. */}
                {!links.files.length && <FieldRow icon={FileText} label="Files" value="None" />}
                {links.files.map((f) => (
                  // The file by name; its id copies from the button and shows whole on hover.
                  <FieldRow
                    key={f.fileId}
                    icon={FileText}
                    label="File"
                    value={f.name ?? <MiddleTruncate text={f.fileId} />}
                    href={f.viewerHref}
                    wrap
                    adornment={<CopyIconButton value={f.fileId} label="file id" />}
                    testId="case-link-file"
                  />
                ))}
                {!links.runs.length && <FieldRow label="Runs" value="None" />}
                {links.runs.map((r) => (
                  <FieldRow key={r.id} label="Run" value={`${r.workflowName} · ${r.state}`} href={r.href} wrap testId="case-link-run" />
                ))}
                {!links.emails.length && <FieldRow icon={Mail} label="Emails" value="None" />}
                {links.emails.map((e) => (
                  <FieldRow key={e.id} icon={Mail} label="Email" value={`${e.subject} · ${relativeTime(e.at)}`} href={e.href} wrap testId="case-link-email" />
                ))}
                {!links.cases.length && <FieldRow label="Other cases" value="None" />}
                {links.cases.map((k) => (
                  <FieldRow
                    key={k.id}
                    label={k.relation === 'same_customer' ? 'Same customer' : 'Linked case'}
                    value={`${k.subject} · ${CASE_STATUS[k.status as CaseStatus] ?? k.status}`}
                    href={k.href}
                    wrap
                    testId="case-link-case"
                  />
                ))}
                <div className="flex flex-wrap gap-x-3 pt-2">
                  <AllLink href={links.runs.length ? links.allHrefs.runs : null} label="All runs" />
                  <AllLink href={links.emails.length ? links.allHrefs.emails : null} label="All emails" />
                  <AllLink href={links.allHrefs.cases} label="All cases for this customer" />
                </div>
              </AttributeCard>
            )}
            <AttributeCard title="Details" icon={SlidersHorizontal} testId="case-details-card">
              <FieldRow label="Status" value={CASE_STATUS[c.status]} testId="case-status" />
              <FieldRow label="Priority" value={CASE_PRIORITY[c.priority]} testId="case-priority" />
              <FieldRow label="Owner" value={owner} testId="case-owner" />
              {c.team && <FieldRow label="Team" value={c.team.name} />}
              {customer && <FieldRow label="Customer" value={customer} href={c.customer?.href} />}
              {c.caseType && <FieldRow label="Case type" value={`${c.caseType.name} · v${c.caseType.version}`} wrap />}
              {c.workflow && <FieldRow label="Workflow" value={c.workflow.name} href={c.workflow.href} wrap />}
              {/* Who opened it is the first line of the activity, by name; the record keeps only an actor id. */}
              <FieldRow label="Opened" value={relativeTime(c.createdAt)} />
            </AttributeCard>
            {paused && (
              <AttributeCard title="Paused" icon={Clock}>
                <p className="text-xs text-muted-foreground">Waiting on the customer since {relativeTime((c.sla?.pausedSince ?? c.pausedSince)!)}. Both deadlines move on by the time it waits.</p>
              </AttributeCard>
            )}
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <ItemGroup className="gap-2">
            {left && (
              <Item variant="outline" size="sm" className="bg-card" data-testid="case-whats-left">
                <ItemMedia variant="icon">{left.items.length ? <ListChecks /> : <CheckCircle2 />}</ItemMedia>
                <ItemContent>
                  {left.items.length ? (
                    <>
                      <ItemTitle>What&apos;s left: waiting on {[...new Set(left.items.map((x) => x.who))].join(', ')}</ItemTitle>
                      {left.items.map((x) => (
                        <ItemDescription key={x.href} className="line-clamp-none">
                          <Link href={x.href} className="underline-offset-4 hover:underline">
                            {x.what}
                          </Link>
                          {x.dueAt ? ` · by ${relativeTime(x.dueAt)}` : ''}
                        </ItemDescription>
                      ))}
                    </>
                  ) : (
                    <>
                      <ItemTitle>Nothing is left on this case</ItemTitle>
                      <ItemDescription className="line-clamp-none">
                        {left.resolvable
                          ? 'Every task is decided and no automation is still running.'
                          : c.status === 'resolved' || c.status === 'closed'
                            ? `The case is ${CASE_STATUS[c.status].toLowerCase()}.`
                            : 'Automation is still working on it.'}
                      </ItemDescription>
                    </>
                  )}
                </ItemContent>
                {left.resolvable && (
                  <ItemActions>
                    <LoadingButton size="sm" isLoading={change.isPending} onClick={resolve} data-testid="case-resolve">
                      Resolve
                    </LoadingButton>
                  </ItemActions>
                )}
              </Item>
            )}
            {c.origin && (
              <Item variant="muted" size="sm" data-testid="case-origin">
                <ItemMedia variant="icon">
                  <PlayCircle />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>How this case started</ItemTitle>
                  <ItemDescription className="line-clamp-none">{c.origin.text}</ItemDescription>
                </ItemContent>
                {c.origin.href && (
                  <ItemActions>
                    <Button asChild size="sm" variant="ghost">
                      <Link href={c.origin.href} data-testid="case-origin-run">
                        See the run
                      </Link>
                    </Button>
                  </ItemActions>
                )}
              </Item>
            )}
          </ItemGroup>
          {fields.length ? (
            <Section title={`About this ${c.caseType?.name.toLowerCase() ?? 'case'}`} bodyClassName="px-4 py-1" id="case-about">
              <div data-testid="case-typed-fields">
                {fields.map((f) => (
                  <FieldRow key={f.key} label={f.label} value={f.display} wrap href={f.fileId ? `/files/${encodeURIComponent(f.fileId)}` : undefined} testId={`case-field-${f.key}`} />
                ))}
              </div>
            </Section>
          ) : (
            c.fields && <CaseFields fields={c.fields} />
          )}

          {actions.length > 0 && (
            <Section title={`Drafted actions (${actions.length})`} bodyClassName="px-4 py-1">
              <ItemGroup data-testid="case-actions">
                {actions.map((a) => (
                  <Item key={a.id} size="sm" className="px-0" data-testid={`case-action-${a.status}`}>
                    <ItemContent>
                      <ItemTitle>{a.label}</ItemTitle>
                      <ItemDescription>{[ACTION_KIND[a.kind] ?? a.kind, a.approvalsNeeded > 1 ? `${a.approvalsGiven} of ${a.approvalsNeeded} approvals` : 'one approver'].join(' · ')}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                      <Badge
                        variant={a.status === 'approved' ? 'secondary' : 'outline'}
                        className={a.status === 'refused' ? 'border-destructive/40 bg-destructive/10 font-normal text-destructive' : 'font-normal'}
                        title={a.status === 'refused' ? 'Approved, but the call answered with an error' : undefined}
                      >
                        {ACTION_STATUS[a.status] ?? a.status}
                      </Badge>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={a.href}>Open</Link>
                      </Button>
                    </ItemActions>
                  </Item>
                ))}
              </ItemGroup>
            </Section>
          )}

          {c.feed && <StoryFeed title="Activity" description="Everything that happened to this case, newest first." lines={c.feed.lines} more={c.feed.more} filters testId="case-feed" />}
        </div>
      </RecordLayout>
      <DialogShell
        open={noteOpen}
        onOpenChange={setNoteOpen}
        title="Add a note"
        description="Notes are kept on the case and shown in its activity."
        onSubmit={addNote}
        footer={
          <>
            <Button variant="outline" onClick={() => setNoteOpen(false)}>
              Cancel
            </Button>
            <LoadingButton isLoading={note.isPending} disabled={!text.trim()} onClick={addNote} data-testid="case-add-note">
              Add note
            </LoadingButton>
          </>
        }
      >
        <FormField id="case-note" label="Note">
          <Textarea id="case-note" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Called the customer; they will send the statement tomorrow" />
        </FormField>
      </DialogShell>
    </PageLayout>
  );
}

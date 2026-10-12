'use client';

import * as React from 'react';
import { AlertTriangle, CheckCircle2, FileArchive, FileText, XCircle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { plural } from '@/lib/format';
import type { SkillCreateInput, SkillDetail, SkillImportPreview, SkillLoading, SkillVersion } from '@/lib/types/skills';

import { DiffView, EDIT_CLASS, EditClassBadge, joinSections } from './skill-meta';
import { SkillLoadingField } from './skill-loading';

function TeamSelect({ id, teams, value, onChange, error }: { id: string; teams: string[]; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <FormField id={id} label="Owner team" error={error} hint="Owns the skill, its reviews and its versions.">
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full" aria-invalid={!!error}>
          <SelectValue placeholder="Choose a team" />
        </SelectTrigger>
        <SelectContent>
          {teams.map((t) => (
            <SelectItem key={t} value={t}>
              {t}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

/** A blank skill: name, when to use it and the owner team. The instructions are written on the skill page. */
export function NewSkillDialog({ open, onOpenChange, teams, defaultTeam, maxUseWhen, isPending, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; teams: string[]; defaultTeam?: string; maxUseWhen: number; isPending: boolean; onSubmit: (i: SkillCreateInput) => Promise<unknown> }) {
  const [name, setName] = React.useState('');
  const [useWhen, setUseWhen] = React.useState('');
  const [loading, setLoading] = React.useState<SkillLoading>('on_match');
  const [team, setTeam] = React.useState('');
  const [errors, setErrors] = React.useState<{ name?: string; useWhen?: string; team?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setName('');
      setUseWhen('');
      setLoading('on_match');
      setTeam('');
      setErrors({});
    }
  }, [open]);
  // Teams can arrive after the dialog opens; pick the default once they do.
  React.useEffect(() => {
    if (open && !team && teams.length) setTeam(defaultTeam && teams.includes(defaultTeam) ? defaultTeam : teams[0]);
  }, [open, team, teams, defaultTeam]);

  const submit = async () => {
    const e = { name: name.trim() ? undefined : 'Name the skill.', useWhen: !useWhen.trim() && loading === 'on_match' ? 'Say when an agent should use it.' : useWhen.length > maxUseWhen ? `Keep it under ${maxUseWhen} characters.` : undefined, team: team ? undefined : 'Choose the owner team.' };
    setErrors(e);
    if (e.name || e.useWhen || e.team) return;
    try {
      await onSubmit({ name: name.trim(), useWhen: loading === 'always' ? '' : useWhen.trim(), loading, instructions: joinSections({ steps: '1. ', rules: '- ', examples: '', output_format: '' }), ownerTeam: team, toolIds: [], knowledgeBases: [], guardrails: [], origin: 'blank' });
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New skill"
      description="Starts as a draft. Write the instructions, tools and tests on the next page."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} onClick={submit} data-testid="new-skill-submit">
            Create skill
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="ns-name" label="Name" error={errors.name}>
          <Input id="ns-name" aria-invalid={!!errors.name} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Statement copy request" />
        </FormField>
        <SkillLoadingField id="ns-loading" value={loading} onChange={setLoading} />
        {loading === 'on_match' && (
          <FormField id="ns-usewhen" label="Use when" error={errors.useWhen} hint={`What the model reads to decide to load it. ${useWhen.length} of ${maxUseWhen} characters.`}>
            <Textarea id="ns-usewhen" aria-invalid={!!errors.useWhen} value={useWhen} onChange={(e) => setUseWhen(e.target.value)} className="min-h-20" placeholder="e.g. Use when a customer asks for a copy of a past statement." />
          </FormField>
        )}
        <TeamSelect id="ns-team" teams={teams} value={team} onChange={setTeam} error={errors.team} />
      </div>
    </DialogShell>
  );
}

/**
 * Import an Agent Skills folder (zip) or a single SKILL.md. The file goes through Files; the server reads its
 * frontmatter and lists what it found before anything is created. Unknown tools are dropped, never granted.
 */
export function ImportSkillDialog({
  open,
  onOpenChange,
  teams,
  defaultTeam,
  onFile,
  preview,
  previewLoading,
  previewError,
  isPending,
  onImport,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  teams: string[];
  defaultTeam?: string;
  /** The uploaded file's id once it passed the scan, so the page can read the preview. */
  onFile: (fileId: string | undefined) => void;
  preview?: SkillImportPreview;
  previewLoading: boolean;
  previewError?: string;
  isPending: boolean;
  onImport: (fileId: string, team: string) => Promise<unknown>;
}) {
  const [upload, setUpload] = React.useState<UploadItem[]>([]);
  const [team, setTeam] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setUpload([]);
      setError(null);
      setTeam('');
      onFile(undefined);
    }
    // Reset only when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  React.useEffect(() => {
    if (open && !team && teams.length) setTeam(defaultTeam && teams.includes(defaultTeam) ? defaultTeam : teams[0]);
  }, [open, team, teams, defaultTeam]);
  const fileId = uploadsReady(upload) ? upload[0].fileId : undefined;
  React.useEffect(() => {
    onFile(fileId);
  }, [fileId, onFile]);
  const waiting = upload.length ? uploadsBlocker(upload) : undefined;
  const blocked = !fileId || !preview || preview.errors.length > 0 || !team;

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Import skill"
      description="A SKILL.md file, or a zip of a skill folder with SKILL.md and its resources. It is created as a draft."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <span className="mr-auto text-xs text-destructive">{error}</span>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={blocked}
            onClick={async () => {
              try {
                await onImport(fileId!, team);
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
            data-testid="import-skill-submit"
          >
            Import as draft
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FileUpload id="skill-import" purpose="skill_resource" types={['md', 'zip']} title="Drop SKILL.md or a skill folder zip" hint="Frontmatter needs name (lowercase, hyphens) and description." onChange={setUpload} testId="skill-import-upload" />
        {waiting && <p className="text-xs text-muted-foreground">{waiting}</p>}
        {fileId && (previewLoading ? <Skeleton className="h-28 w-full" /> : previewError ? <p className="text-sm text-destructive">{previewError}</p> : preview && <ImportPreview preview={preview} />)}
        <TeamSelect id="is-team" teams={teams} value={team} onChange={setTeam} />
      </div>
    </DialogShell>
  );
}

function ImportPreview({ preview: p }: { preview: SkillImportPreview }) {
  return (
    <div className="flex flex-col gap-2 rounded-md border p-3 text-sm" data-testid="skill-import-preview">
      <div className="flex items-center gap-2 font-medium">
        {p.format === 'folder_zip' ? <FileArchive className="size-4 text-muted-foreground" /> : <FileText className="size-4 text-muted-foreground" />}
        {p.name || p.fileName}
        {p.slug && <code className="font-mono text-xs text-muted-foreground">{p.slug}</code>}
      </div>
      {p.useWhen && <p className="text-xs text-muted-foreground">{p.useWhen}</p>}
      <div className="text-xs">
        <span className="text-muted-foreground">Tools: </span>
        {p.tools.length ? p.tools.map((t) => (t.toolId ? t.name : `${t.requested} (dropped)`)).join(', ') : 'none'}
        {p.resources.length > 0 && (
          <>
            <span className="text-muted-foreground"> · Resources: </span>
            {p.resources.map((r) => r.name).join(', ')}
          </>
        )}
      </div>
      {p.errors.map((e) => (
        <p key={e} className="flex items-start gap-1.5 text-xs text-destructive">
          <XCircle className="mt-0.5 size-3.5 shrink-0" /> {e}
        </p>
      ))}
      {p.warnings.map((w) => (
        <p key={w} className="flex items-start gap-1.5 text-xs text-warning-text">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {w}
        </p>
      ))}
      {!p.errors.length && (
        <p className="flex items-center gap-1.5 text-xs text-success-text">
          <CheckCircle2 className="size-3.5" /> Ready to import
        </p>
      )}
    </div>
  );
}

/** Sends the newest draft to Reviews. Shows what the reviewer will see: edit class, approvers needed and the test result. */
export function RequestReviewDialog({ open, onOpenChange, skill, isPending, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; skill: SkillDetail; isPending: boolean; onSubmit: (note: string) => Promise<unknown> }) {
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setNote(skill.versions[0]?.note ?? '');
      setError(null);
    }
  }, [open, skill.versions]);
  const v = skill.versions[0];
  const check = skill.publishCheck;
  const run = v?.testRun;
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Request review of v${v?.version}`}
      description={`A publisher in ${skill.ownerTeam} other than you decides it in Reviews. Agents keep their pinned version until someone moves them.`}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <span className="mr-auto text-xs text-destructive">{error}</span>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={!check.canRequest}
            onClick={async () => {
              if (!note.trim()) return setError('Say what changed and why.');
              try {
                await onSubmit(note.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
            data-testid="request-review-submit"
          >
            Send to Reviews
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <EditClassBadge editClass={check.editClass} />
          <span className="text-muted-foreground">{EDIT_CLASS[check.editClass].hint}</span>
        </div>
        <p>
          {run ? (
            <>
              Tests on v{run.version}: <span className={run.passed === run.total ? 'font-medium text-success-text' : 'font-medium text-warning-text'}>{run.passed} of {plural(run.total, 'case')} pass</span>
              {run.passed < run.total && '. The approver must give a reason to publish with failures.'}
            </>
          ) : (
            'No test run on this version.'
          )}
        </p>
        {!check.canRequest && (
          <ul className="flex flex-col gap-1 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-destructive" data-testid="request-review-blockers">
            {check.blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        <FormField id="rr-note" label="What changed and why">
          <Textarea id="rr-note" value={note} onChange={(e) => (setNote(e.target.value), setError(null))} className="min-h-20" placeholder="e.g. Adds the posted-payment warning Lending Servicing asked for." />
        </FormField>
      </div>
    </DialogShell>
  );
}

/** Reason-required deprecation for one or several skills. */
export function DeprecateSkillDialog({ open, onOpenChange, names, pinnedBy, isPending, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; names: string[]; pinnedBy: number; isPending: boolean; onSubmit: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
    }
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={names.length === 1 ? `Deprecate ${names[0]}?` : `Deprecate ${plural(names.length, 'skill')}?`}
      description={`No agent can attach ${names.length === 1 ? 'it' : 'them'} again.${pinnedBy ? ` ${plural(pinnedBy, 'agent')} keep${pinnedBy === 1 ? 's' : ''} the pinned version and ${pinnedBy === 1 ? 'sees' : 'see'} a prompt to replace it.` : ''}`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            variant="destructive"
            onClick={async () => {
              if (!reason.trim()) return setError('Give a reason. Owners of agents that pin it will read it.');
              try {
                await onSubmit(reason.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
            data-testid="deprecate-submit"
          >
            Deprecate
          </LoadingButton>
        </div>
      }
    >
      <FormField id="dep-reason" label="Reason" error={error ?? undefined}>
        <Textarea id="dep-reason" aria-invalid={!!error} value={reason} onChange={(e) => (setReason(e.target.value), setError(null))} className="min-h-20" placeholder="e.g. Replaced by the case triage skill" />
      </FormField>
    </DialogShell>
  );
}

/** Compare two versions: fields, then the instructions line by line. */
export function VersionDiffDialog({ open, onOpenChange, versions, from, to, onChange }: { open: boolean; onOpenChange: (o: boolean) => void; versions: SkillVersion[]; from: number; to: number; onChange: (from: number, to: number) => void }) {
  const a = versions.find((v) => v.version === from);
  const b = versions.find((v) => v.version === to);
  const field = (label: string, x: string, y: string) =>
    x === y ? null : (
      <div key={label} className="grid grid-cols-[120px_1fr] gap-2 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span>
          <span className="bg-destructive/10 text-destructive line-through">{x || 'None'}</span> → <span className="bg-success/10 text-success-text">{y || 'None'}</span>
        </span>
      </div>
    );
  const pick = (value: number, set: (v: number) => void, label: string) => (
    <Select value={String(value)} onValueChange={(v) => set(Number(v))}>
      <SelectTrigger className="w-28" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {versions.map((v) => (
          <SelectItem key={v.version} value={String(v.version)}>
            v{v.version}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
  return (
    <DialogShell open={open} onOpenChange={onOpenChange} size="lg" title="Compare versions" description="Removed lines are struck through; added lines are highlighted." data-testid="version-diff-dialog">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2 text-sm">
          {pick(from, (v) => onChange(v, to), 'From version')} <span className="text-muted-foreground">to</span> {pick(to, (v) => onChange(from, v), 'To version')}
        </div>
        {a && b && (
          <>
            <div className="flex flex-col gap-1.5">
              {[
                field('Name', a.content.name, b.content.name),
                field('Use when', a.content.useWhen, b.content.useWhen),
                field('Tools', a.content.tools.map((t) => t.name).join(', '), b.content.tools.map((t) => t.name).join(', ')),
                field('Knowledge bases', a.content.knowledgeBases.join(', '), b.content.knowledgeBases.join(', ')),
                field('Guardrails', a.content.guardrails.join(' · '), b.content.guardrails.join(' · ')),
                field('Resources', a.content.resources.map((r) => r.name).join(', '), b.content.resources.map((r) => r.name).join(', ')),
              ]}
            </div>
            <DiffView before={a.content.instructions} after={b.content.instructions} testId="version-diff" />
          </>
        )}
      </div>
    </DialogShell>
  );
}

/** A text template kept on the version, e.g. a reply skeleton the steps fill in. */
export function TemplateResourceDialog({ open, onOpenChange, isPending, onSubmit }: { open: boolean; onOpenChange: (o: boolean) => void; isPending: boolean; onSubmit: (t: { name: string; body: string }) => Promise<unknown> }) {
  const [name, setName] = React.useState('');
  const [body, setBody] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setName('');
      setBody('');
      setError(null);
    }
  }, [open]);
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Add template"
      description="Saved on the draft version. Use {{field}} for values the steps fill in."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <span className="mr-auto text-xs text-destructive">{error}</span>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              if (!name.trim() || !body.trim()) return setError('A template needs a name and text.');
              try {
                await onSubmit({ name: name.trim(), body });
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Add template
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="tr-name" label="Name">
          <Input id="tr-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Statement copy reply" />
        </FormField>
        <FormField id="tr-body" label="Text">
          <Textarea id="tr-body" value={body} onChange={(e) => setBody(e.target.value)} className="min-h-40 font-mono text-xs" placeholder="e.g. Hi {{firstName}}, the statement you asked for is attached." />
        </FormField>
      </div>
    </DialogShell>
  );
}

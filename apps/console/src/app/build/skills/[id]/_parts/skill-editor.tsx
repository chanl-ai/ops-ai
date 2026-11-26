'use client';

import * as React from 'react';
import { BookOpen, CircleAlert, Lock, RefreshCw, TriangleAlert, Users, Wrench } from 'lucide-react';

import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { LeaveGuard } from '@/components/shared/leave-guard';
import { ListSection, type ListRow } from '@/components/shared/list-section';
import { NewerCopyNotice } from '@/components/shared/newer-copy-notice';
import { RecordLayout } from '@/components/shared/record-layout';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { parseText } from '@/components/shared/instruction-document/document-model';
import { mentionToken } from '@/lib/mentions';
import { RichTextEditor, type RichTextEditorHandle } from '@/components/shared/rich-text-editor';
import { SkillInputsSection } from '@/components/skills/skill-inputs-section';
import { UNWRITTEN_SECTIONS } from '@/components/skills/skill-meta';
import { inText, refusedSave } from '@/components/skills/skill-problems';
import { SkillResultsSection, type SkillEndingValue } from '@/components/skills/skill-results-section';
import { SkillWhenSection, type SkillWhen, type SkillWhenHandle } from '@/components/skills/skill-when-section';
import { AccessBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { knowledgeBaseOptions, linkToolOptions, useOptionLabels } from '@/hooks/options-queries';
import { useReferenceLabels } from '@/hooks/references-queries';
import { useReloadToRead } from '@/hooks/use-reload-to-read';
import { useSaveSkillDraft, useSkill, useSkillOptions, useSkillTextReading } from '@/hooks/skill-queries';
import { SKILL_LOADING_OPTIONS } from '@/components/skills/skill-loading';
import { useAutosave } from '@/hooks/use-autosave';
import { carriedAfterSave } from '@/lib/autosave';
import type { SaveStatus } from '@/lib/save-state-gate';
import { plural } from '@/lib/format';
import { type Carried, keptEdits } from '@/lib/kept-edits';
import { baseOf, staleNote, staleSave } from '@/lib/save-base';
import type { PublishBlocker } from '@/lib/types/references';
import type { SkillDetail, SkillInputField, SkillLoading, SkillPartContent } from '@/lib/types/skills';

import { useCanBuild } from '@/hooks/me-queries';
import { PartsList } from './parts-section';
import { skillBody } from './skill-body';
import { nameError } from '@/lib/validation/names';

/** What the page's header shows and does for the editor's autosave. */
export interface SkillSaveState {
  status: SaveStatus;
  detail: string | null;
  saveNow: () => void;
  retry: () => void;
  canSave: boolean;
}

export interface Form {
  name: string;
  when: SkillWhen;
  loading: SkillLoading;
  instructions: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
  refusal: string;
  parts: SkillPartContent[];
  /** The skill as text: what it says and, for a skill without parts, its steps. */
  text: string;
  ending: SkillEndingValue;
  inputs: SkillInputField[];
}

// A skill made blank holds only section headings; its text opens empty so the worked example shows instead.
const squash = (t: string) => t.replace(/\s+/g, '');
const textOf = (text: string) => (squash(text) === squash(UNWRITTEN_SECTIONS) ? '' : text);
const formOf = (sk: SkillDetail): Form => ({ name: sk.content.name, when: { useWhen: sk.content.useWhen, notWhen: sk.content.notWhen ?? '' }, loading: sk.content.loading, instructions: sk.content.instructions, toolIds: sk.content.tools.map((t) => t.toolId), knowledgeBases: sk.content.knowledgeBases, guardrails: sk.content.guardrails, refusal: sk.content.refusal ?? '', parts: sk.content.parts ?? [], text: textOf(sk.text), ending: { exit: sk.content.exit ?? {}, returns: sk.content.returns ?? [], success: sk.content.success ?? [] }, inputs: sk.content.inputs ?? [] });
const NONE: PublishBlocker[] = [];
const KINDS = [['tools', 'tool', 'tools'], ['knowledge', 'knowledge source', 'knowledge sources'], ['skills', 'skill', 'skills'], ['agents', 'agent', 'agents'], ['workflows', 'workflow', 'workflows']] as const;
/** “3 tools · 2 knowledge sources”, from the counts the service read from the text. */
const usesLine = (uses: Record<(typeof KINDS)[number][0], number> | undefined) => {
  const parts = KINDS.filter(([k]) => uses?.[k]).map(([k, one, many]) => `${uses![k]} ${uses![k] === 1 ? one : many}`);
  return parts.length ? parts.join(' · ') : undefined;
};
/**
 * The person's own text, kept read-only on the page after someone else saved first and the person reloaded: the
 * editor shows the other person's text, and nothing saves over it unless the person uses this copy.
 */
export interface KeptText {
  text: string;
  note: string;
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/**
 * The newest version as a form: when to use the skill, its notes and steps as one document, then its settings. Saving
 * edits the open draft, or opens a new draft on top of the published version; nothing reaches an agent until a
 * publisher approves it. The unsaved bar says which edit class the change is. A person who may not change the team's
 * skills (`canEdit` false) reads the same form with every field off and no save.
 */
export function SkillEditor({ skill: sk, tab = 'instructions', hidden, rail, canEdit, onDirtyChange, onSaveState, carried, keptText }: { skill: SkillDetail; tab?: 'instructions' | 'settings'; /** Kept mounted under another tab (Tests), so unsaved edits stay. */ hidden?: boolean; rail?: React.ReactNode; canEdit: boolean; onDirtyChange?: (dirty: boolean) => void; onSaveState?: (s: SkillSaveState) => void; carried?: React.RefObject<Carried<Form> | null>; keptText?: React.RefObject<KeptText | null> }) {
  const save = useSaveSkillDraft(sk.id);
  const current = useSkill(sk.id);
  const options = useSkillOptions();
  const saved = React.useMemo(() => formOf(sk), [sk]);
  // The page owns the unsaved edits (`carried`): the form is drawn again on a resize (the page's columns stack below
  // 1024px) and on a newer version after Reload, and each time starts from the saved version with those edits on top.
  const [form, setForm] = React.useState<Form>(() => (carried?.current ? keptEdits(carried.current.readBefore, carried.current.edited, saved) : saved));
  const [endingValid, setEndingValid] = React.useState(true);
  const [whenValid, setWhenValid] = React.useState(true);
  const [inputsValid, setInputsValid] = React.useState(true);
  // A mention the team no longer holds is the one thing in the text that blocks a save; free text never does.
  const [brokenMentions, setBrokenMentions] = React.useState(0);
  const setEnding = React.useCallback((ending: SkillEndingValue) => setForm((f) => ({ ...f, ending })), []);
  const setWhen = React.useCallback((when: SkillWhen) => setForm((f) => ({ ...f, when })), []);
  const setInputs = React.useCallback((inputs: SkillInputField[]) => setForm((f) => ({ ...f, inputs })), []);
  const whenForm = React.useRef<SkillWhenHandle>(null);
  const textDoc = React.useRef<RichTextEditorHandle>(null);
  const context = React.useMemo(() => ({ forSkill: sk.id }), [sk.id]);
  const reading = useSkillTextReading(sk.id, form.text, { loading: form.loading, hasParts: form.parts.length > 0, exit: form.ending.exit });
  const mentioned = React.useMemo(() => [...new Set(parseText(form.text).flatMap((x) => (x.t === 'ref' ? [mentionToken(x).slice(1)] : [])))], [form.text]);
  const labels = useReferenceLabels({ forSkill: sk.id }, mentioned);
  // A step's first line, from the reader's last answer; line 1 until it has answered.
  const lineOfStep = (step: number) => reading.reading?.stepLines[step - 1] ?? 1;
  // The person's text from before a Reload, held by the page so a redraw keeps it until they use it or drop it.
  const [mine, setMine] = React.useState<KeptText | null>(() => keptText?.current ?? null);
  const [mineOpen, setMineOpen] = React.useState(false);
  React.useEffect(() => {
    if (keptText) keptText.current = mine;
  }, [keptText, mine]);
  // A save refused for one step, shown on that step until the steps change.
  const [refused, setRefused] = React.useState<PublishBlocker | null>(null);
  // A skill has steps or parts, never both: one with parts keeps its Markdown introduction, edited in the same editor.
  const canBuildSkills = useCanBuild('skills');
  const body = skillBody(form);
  const stepped = body.field === 'text';
  const newest = sk.versions[0];
  const locked = newest.state === 'in_review' ? `v${newest.version} is waiting in Reviews.` : sk.status === 'deprecated' ? 'The skill is deprecated. Duplicate it to change it.' : undefined;
  // The document editor and the save bar sit outside what a disabled fieldset reaches, so they read this.
  const readOnly = !!locked || !canEdit;
  const changed = {
    wording: form.name !== saved.name || form.when.useWhen !== saved.when.useWhen || form.when.notWhen.trim() !== saved.when.notWhen.trim() || form.loading !== saved.loading || form.instructions !== saved.instructions || form.text !== saved.text || JSON.stringify([form.parts, form.ending, form.inputs]) !== JSON.stringify([saved.parts, saved.ending, saved.inputs]),
    scope: !same(form.toolIds, saved.toolIds) || !same(form.knowledgeBases, saved.knowledgeBases) || !same(form.guardrails, saved.guardrails) || form.refusal.trim() !== saved.refusal.trim(),
  };
  const dirty = changed.wording || changed.scope;
  // Set while a save is in flight: the saved version redraws the form, and the edits it saved are not carried onto it.
  const saving = React.useRef(false);
  const formNow = React.useRef(form);
  formNow.current = form;
  React.useEffect(() => {
    if (carried && !saving.current) carried.current = dirty ? { readBefore: saved, edited: form } : null;
  }, [carried, dirty, saved, form]);
  // The page holds back what would redraw this form (a file added, a version restored) while there is unsaved text.
  React.useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  const limit = options.data?.limits.useWhenMaxChars ?? 1024;
  const textMax = options.data?.limits.instructionsMaxChars ?? 24000;
  const textLength = (stepped ? form.text : form.instructions).length;
  const errors = { name: nameError(form.name, 'Name the skill.') };
  const found = React.useMemo(() => (newest.state === 'draft' ? inText(sk.publishCheck.problems ?? NONE) : NONE), [newest.state, sk.publishCheck.problems]);
  const problems = React.useMemo(() => (refused ? [...found, refused] : found), [found, refused]);
  // A missing list from an older service is none.
  const warnings = newest.state === 'draft' ? sk.publishCheck.warnings : undefined;
  const tools = options.data?.tools ?? [];
  // A skill written as text runs the tools its text mentions; one kept on the form from before stays listed, removable.
  const textTools = mentioned.filter((t) => t.startsWith('tool:')).map((t) => t.slice('tool:'.length));
  const listedTools = stepped ? [...new Set([...textTools, ...form.toolIds])] : form.toolIds;
  const labelOf = (id: string) => labels.data?.find((l) => l.kind === 'tool' && l.id === id)?.label;
  const toolOf = (id: string) => tools.find((t) => t.toolId === id) ?? sk.content.tools.find((t) => t.toolId === id);

  // Everything the form needs to be saved: a valid name, parts, when, endings and inputs.
  const valid = !errors.name && endingValid && whenValid && inputsValid && !brokenMentions;
  const sentForm = React.useRef<Form>(form);
  const send = () => {
    sentForm.current = form;
    saving.current = true;
    if (carried) carried.current = null;
    // A skill saved as a list of steps keeps them until its text is changed; one written as text sends its text.
    const text = form.text !== saved.text || sk.content.source !== undefined ? { source: form.text } : {};
    return save.mutateAsync({ name: form.name, useWhen: form.when.useWhen, loading: form.loading, ...(stepped ? {} : { instructions: form.instructions }), toolIds: form.toolIds, knowledgeBases: form.knowledgeBases, guardrails: form.guardrails, refusal: form.refusal.trim(), parts: form.parts, ...(stepped ? { inputs: form.inputs, ...text, notWhen: form.when.notWhen.trim(), exit: form.ending.exit, returns: form.ending.returns, success: form.ending.success } : {}), ...baseOf(sk) });
  };
  // The page remounts this form when a newer version arrives, and the new form takes the person's unsaved edits from
  // `carried`. With nothing newer the form stays as it is. Either way nothing the person typed is dropped.
  // The text is one field, so carried whole it would replace theirs: the form takes their text, and the person's own
  // text is kept read-only beside it. Every other field the person changed is carried onto their version. The page
  // draws a new form once its props hold the copy read; this one stays paused until then, and finishes the reload
  // itself only when nothing newer was read.
  const readAgain = React.useCallback(async () => (await current.refetch({ throwOnError: true })).data?.digest, [current]);
  const { reload: readNewest, reading: reloading } = useReloadToRead(sk.digest, readAgain, () => {
    // Nothing newer was read, so this form is still the newest one and keeps the person's text as it is.
    auto.clearStale();
    if (keptText) keptText.current = null;
  });
  const reload = async () => {
    if (keptText) keptText.current = form.text !== saved.text ? { text: form.text, note: auto.stale ?? '' } : null;
    if (carried) carried.current = { readBefore: saved, edited: { ...form, text: saved.text } };
    await readNewest();
  };
  const takeMine = () => mine && (setForm((f) => ({ ...f, text: mine.text })), setMine(null), setMineOpen(false));
  const dropMine = () => (setMine(null), setMineOpen(false));
  // The saved version redraws the form, so what was typed while the save was in flight is carried onto it.
  const auto = useAutosave({
    waiting: dirty && valid ? JSON.stringify(form) : null,
    enabled: !readOnly,
    paused: reloading,
    settledOn: sk.digest,
    send,
    onSaved: () => {
      const kept = carriedAfterSave(sentForm.current, formNow.current, sentForm.current);
      if (carried) carried.current = kept && { readBefore: sentForm.current, edited: kept };
      saving.current = false;
    },
    refusal: (e) => {
      saving.current = false;
      // In review and deprecated are 409 as well; only a newer version offers a reload.
      const newer = staleSave(e);
      if (carried) carried.current = { readBefore: saved, edited: formNow.current };
      return newer ? { stale: staleNote(newer) } : null;
    },
    onError: (e) => {
      const onStep = refusedSave(e);
      if (onStep?.position?.step) setRefused(onStep);
    },
  });
  const { stale, error: failed } = auto;
  const status: SaveStatus = reloading ? 'saving' : auto.status;
  React.useEffect(() => {
    onSaveState?.({ status, detail: stale ?? failed ?? (dirty && !valid ? 'Fix the highlighted fields to save' : null), saveNow: auto.saveNow, retry: auto.retry, canSave: !readOnly && dirty && valid && !stale });
  });

  // Agents are left out: a pick on a skill written as steps is typed as a tool mention, which an agent is not.
  const toolLabels = new Map((useOptionLabels(linkToolOptions, listedTools).data?.data ?? []).map((o) => [o.id, o]));
  const kbLabels = new Map((useOptionLabels(knowledgeBaseOptions, form.knowledgeBases).data?.data ?? []).map((o) => [o.id, o]));
  // A skill written as steps uses the tools its text mentions, so a pick from the list is typed into the text as a mention.
  const pickTools = (ids: string[]) => {
    const added = ids.filter((id) => !listedTools.includes(id));
    const removed = listedTools.filter((id) => !ids.includes(id) && !(stepped && textTools.includes(id)));
    if (stepped) for (const id of added) textDoc.current?.insert(`${mentionToken({ kind: 'tool', id })} `);
    setForm((f) => ({ ...f, toolIds: [...f.toolIds.filter((x) => !removed.includes(x)), ...(stepped ? [] : added)] }));
  };
  const toolRows: ListRow[] = listedTools.map((id) => {
    const t = toolOf(id);
    const fromText = stepped && textTools.includes(id);
    const name = toolLabels.get(id)?.label ?? t?.name ?? labelOf(id) ?? id;
    return {
      id,
      title: name,
      description: fromText ? 'In the steps' : (toolLabels.get(id)?.hint ?? t?.module),
      state: t ? <AccessBadge access={t.access} /> : undefined,
      remove: fromText || readOnly ? undefined : { label: `Remove ${name}`, onClick: () => setForm((f) => ({ ...f, toolIds: f.toolIds.filter((x) => x !== id) })) },
    };
  });
  const kbRows: ListRow[] = form.knowledgeBases.map((id) => {
    const name = kbLabels.get(id)?.label ?? id;
    return { id, title: name, description: kbLabels.get(id)?.hint ?? undefined, remove: readOnly ? undefined : { label: `Remove ${name}`, onClick: () => setForm((f) => ({ ...f, knowledgeBases: f.knowledgeBases.filter((x) => x !== id) })) } };
  });

  return (
    <div className={hidden ? 'hidden' : 'flex flex-col gap-4'} data-testid="skill-editor">
      {/* The kept copy lives only on this page, so leaving with it asks first. */}
      <LeaveGuard unsaved={(dirty && !readOnly) || !!mine} failed={!!failed} />
      {locked && <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{locked} Fields are read-only.</p>}
      {stale && (
        <Alert data-testid="skill-stale-base">
          <Users />
          <AlertTitle>Someone else saved this skill</AlertTitle>
          <AlertDescription>
            <p>{stale} Nothing was saved. Reload shows their text; yours is kept on this page as a read-only copy beside it, and your other changes stay on their version. Nothing is saved over their text unless you choose to.</p>
            <Button variant="outline" size="sm" onClick={() => void reload()} disabled={reloading} data-testid="skill-stale-reload">
              <RefreshCw className="size-3.5" /> Reload
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {mine && (
        <NewerCopyNotice
          testId="skill-kept-copy"
          title="You are looking at their text"
          copyOpen={mineOpen}
          onToggleCopy={() => setMineOpen((v) => !v)}
          actions={
            <>
              <Button variant="outline" size="sm" disabled={readOnly} onClick={takeMine} data-testid="skill-kept-copy-use">
                Use mine
              </Button>
              <Button variant="ghost" size="sm" onClick={dropMine} data-testid="skill-kept-copy-drop">
                Discard
              </Button>
            </>
          }
        >
          <p>{mine.note} Your unsaved text is kept on this page, read-only, until you drop it or leave. Copy what you need from it into theirs, or use it in place of theirs.</p>
        </NewerCopyNotice>
      )}
      {failed && !stale && (
        <Alert data-testid="skill-save-failed">
          <CircleAlert />
          <AlertTitle>Your last change didn’t save</AlertTitle>
          <AlertDescription>
            <p>It is kept on this page. Check your connection, then retry.</p>
            <p className="text-xs">{failed}</p>
            <Button variant="outline" size="sm" onClick={auto.retry} disabled={auto.saving} data-testid="skill-save-retry">
              <RefreshCw className="size-3.5" /> Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {problems.length > 0 && (
        <Alert data-testid="skill-publish-problems">
          <TriangleAlert />
          <AlertTitle>{found.length ? 'Can’t publish yet' : 'Couldn’t save'}</AlertTitle>
          <AlertDescription>
            <p>
              {plural(problems.length, 'problem')}. Fix {problems.length === 1 ? 'it' : 'them'} in the text and save again.
            </p>
            {problems.map((p, i) => (
              <p key={i} className="flex flex-wrap items-center gap-x-2" data-testid="skill-problem">
                <span>{p.message}</span>
                {p.position?.field === 'steps' && p.position.step && (
                  <Button variant="link" size="sm" onClick={() => textDoc.current?.focusLine(lineOfStep(p.position!.step!))}>
                    Step {p.position.step}
                  </Button>
                )}
                {p.position?.field === 'source' && p.position.index && (
                  <Button variant="link" size="sm" onClick={() => textDoc.current?.focusLine(p.position!.index!)} data-testid="skill-problem-line">
                    Line {p.position.index}
                  </Button>
                )}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
      <div className={tab === 'instructions' ? undefined : 'hidden'} data-testid="skill-instructions-tab">
        <RecordLayout
          railRight
          rail={
            <>
              <ListSection
                id="skill-tools"
                icon={Wrench}
                title="Tools"
                count={listedTools.length}
                description="An agent must have each of these before it can use the skill."
                add={readOnly ? undefined : <EntityPicker source={linkToolOptions} value={listedTools} onChange={pickTools} showChosen={false} addLabel="Add" searchPlaceholder="Search tools by name or system…" emptyText="No tool matches." testId="skill-tools-picker" />}
                rows={toolRows}
                empty="Mention a tool with @ in the steps and it shows here."
              />
              <ListSection
                id="skill-knowledge"
                icon={BookOpen}
                title="Knowledge"
                count={form.knowledgeBases.length}
                add={readOnly ? undefined : <EntityPicker source={knowledgeBaseOptions} value={form.knowledgeBases} onChange={(ids) => setForm((f) => ({ ...f, knowledgeBases: ids }))} showChosen={false} addLabel="Add" searchPlaceholder="Search knowledge bases…" emptyText="No knowledge base matches." testId="skill-knowledge-picker" />}
                rows={kbRows}
                empty="No knowledge yet. Add the documents the steps cite, for example Outage handbook."
              />
              {rail}
            </>
          }
        >
          <div className="flex flex-col gap-4">
            <SkillWhenSection value={form.when} onChange={setWhen} onValidity={setWhenValid} useWhenMax={limit} needsUseWhen={form.loading === 'on_match'} showNotWhen={stepped} notWhenProblem={problems.find((p) => p.position?.field === 'notWhen')?.message} disabled={readOnly} controls={whenForm} />
            <section className="flex flex-col rounded-lg border bg-card" data-testid="skill-text-editor">
              <header className="flex items-center gap-2 border-b px-4 py-2">
                <h2 className="flex-1 text-sm font-semibold">{stepped ? 'Steps' : 'Introduction'}</h2>
                {readOnly ? (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="sop-read-only">
                    <Lock className="size-3.5" /> {locked ?? 'Read only. A builder in its team can change it.'}
                  </span>
                ) : null}
              </header>
              <RichTextEditor
                value={stepped ? form.text : form.instructions}
                onChange={(text) => (setRefused(null), setForm((f) => (stepped ? { ...f, text } : { ...f, instructions: text })))}
                readOnly={readOnly}
                labels={labels.data}
                onMissingChange={(refs) => setBrokenMentions(refs.length)}
                context={context}
                controls={textDoc}
                placeholder={stepped ? 'e.g. Ask for the postcode, then look up the outage with @Outage map. Type / for an if or otherwise path.' : 'e.g. Ask which order it is about, then pick the part that fits.'}
                ariaLabel={stepped ? 'Steps' : 'Introduction'}
              />
              {/* One row on a wide screen: what the text uses on the left, the keys on the right. */}
              <footer className="flex flex-col gap-1 border-t px-4 py-2 text-xs text-muted-foreground tabular-nums sm:flex-row sm:items-center sm:justify-between" data-testid="skill-text-uses">
                <span>{reading.isError ? 'Couldn’t read the text just now; it still saves.' : (usesLine(reading.reading?.uses) ?? 'Mention a tool or knowledge with @ in the steps and it shows here.')}</span>
                <span className="flex items-center gap-3">
                  {/* The server refuses past the limit; the count turns amber from 90 percent so a long paste is caught here. */}
                  <span className={textLength > textMax ? 'text-destructive-text' : textLength >= textMax * 0.9 ? 'text-warning-text' : undefined} data-testid="skill-text-count">
                    {textLength.toLocaleString()} of {textMax.toLocaleString()} characters{textLength > textMax ? ': shorten it to save' : ''}
                  </span>
                  <span>@ mention · Tab indents</span>
                </span>
              </footer>
            </section>
            {mine && mineOpen && (
              <div className="rounded-lg border bg-muted/40" data-testid="skill-kept-copy-text">
                <p className="flex items-center gap-2 border-b px-3 py-2 text-xs text-muted-foreground">
                  <Lock className="size-3.5" /> Your copy, read only. It is not saved.
                </p>
                <RichTextEditor value={mine.text} onChange={() => undefined} readOnly labels={labels.data} context={context} ariaLabel="Your copy of the skill text" />
              </div>
            )}
            {!!reading.reading?.hints.length && reading.forText === form.text && (
              <div className="flex flex-col gap-1 rounded-md border px-3 py-2" data-testid="sop-hints">
                <span className="text-xs font-medium">{plural(reading.reading.hints.length, 'hint')} · nothing here stops a save</span>
                {reading.reading.hints.map((h, k) => (
                  <p key={k} className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground" data-testid="sop-hint">
                    <span>{h.message}</span>
                    <Button variant="link" size="sm" onClick={() => textDoc.current?.focusLine(h.line)}>
                      Line {h.line}
                    </Button>
                  </p>
                ))}
              </div>
            )}
            {body.parts.length > 0 && <PartsList parts={body.parts} ownerTeam={sk.ownerTeam} knowledgeBases={form.knowledgeBases} canSplit={!readOnly && canBuildSkills} />}
          </div>
        </RecordLayout>
      </div>

      <div className={tab === 'settings' ? 'flex flex-col gap-4' : 'hidden'} data-testid="skill-settings-tab">
        <SettingsSection title="Name and loading" description="Loads “When a message matches” (the agent picks it from the Use when line) or “Always” (added to every reply, for wording every agent must use, such as a recorded-call notice).">
          <div className="flex flex-col gap-4">
            <FormField id="si-name" label="Name" error={errors.name}>
              <Input id="si-name" value={form.name} disabled={readOnly} onChange={(e) => setForm({ ...form, name: e.target.value })} className="bg-card" />
            </FormField>
            <FormField id="si-loading" label="Loads">
              <Select value={form.loading} disabled={readOnly} onValueChange={(v) => setForm({ ...form, loading: v as SkillLoading })}>
                <SelectTrigger id="si-loading" className="w-48 bg-card" data-testid="skill-loading-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SKILL_LOADING_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
        </SettingsSection>

        <SettingsSection title="Guardrails" description="Added to the turn while the skill is loaded. They only restrict; they never widen access. Changing them needs two reviewers.">
          <div className="flex flex-col gap-4">
            <FormField id="si-guardrails" label="Guardrails">
              <TagInput id="si-guardrails" value={form.guardrails} onChange={(g) => setForm({ ...form, guardrails: g })} disabled={readOnly} placeholder="e.g. Never promise a restore time the outage map does not give" className="bg-card" />
            </FormField>
            <FormField id="si-refusal" label="When a guardrail refuses, say" hint="What the customer reads instead.">
              <Textarea id="si-refusal" rows={2} value={form.refusal} onChange={(e) => setForm({ ...form, refusal: e.target.value })} disabled={readOnly || !form.guardrails.length} placeholder="e.g. I can’t discuss that here. I can log the outage for you." className="bg-card" data-testid="skill-refusal" />
            </FormField>
          </div>
        </SettingsSection>

        {/* A skill with parts takes its inputs on each part. */}
        {stepped && <SkillInputsSection value={saved.inputs} onChange={setInputs} onValidity={setInputsValid} disabled={readOnly} />}
        {stepped && <SkillResultsSection value={saved.ending} onChange={setEnding} onValidity={setEndingValid} disabled={readOnly} />}
      </div>
    </div>
  );
}

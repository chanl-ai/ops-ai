import { type Fragment, type FragmentField, UiFragment } from './ui-fragment';

/**
 * One screen drawn large, with a numbered note pinned to each part that protects the reader, listed beside it in the
 * same order. Written in markdown as `<!-- site: annotated -->` above a list (src/lib/remark-ops-ai.mjs); a field
 * with a nested bullet carries that bullet as its note.
 */
export function AnnotatedFigure({ data, caption }: { data: string; caption?: string }) {
  const fragment = JSON.parse(data) as Fragment;
  const pins = new Map<FragmentField | 'actions', number>();
  const notes: { label: string; note: string }[] = [];
  for (const f of fragment.fields) {
    if (!f.note) continue;
    notes.push({ label: f.label, note: f.note });
    pins.set(f, notes.length);
  }
  if (fragment.actionsNote) {
    notes.push({ label: fragment.actions.join(' or '), note: fragment.actionsNote });
    pins.set('actions', notes.length);
  }
  return (
    <figure className="ops-figure ops-fig not-prose">
      <div className="ops-fig-stage">
        <div className="ops-annotated">
        <div className="ops-annotated-screen">
          <UiFragment fragment={fragment} pins={pins} size="lg" />
        </div>
        <ol className="ops-annotated-notes">
          {notes.map((n, i) => (
            <li key={n.label}>
              <span className="ops-pin" aria-hidden>
                {i + 1}
              </span>
              <div>
                <p className="ops-annotated-label">{n.label}</p>
                <p>{n.note}</p>
              </div>
            </li>
          ))}
        </ol>
        </div>
      </div>
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

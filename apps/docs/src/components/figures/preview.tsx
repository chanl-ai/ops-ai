import {
  Bot,
  Database,
  FileText,
  Folder,
  FolderOpen,
  Gavel,
  House,
  Inbox,
  List,
  ListChecks,
  type LucideIcon,
  Route,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  UserCheck,
  Wrench,
} from 'lucide-react';

import { CONSOLE_NAV } from './markdown.mjs';
import { pinsFor } from './notes';
import { FigureFrame, Pin, PinNotes } from './parts';
import { type Fragment, UiFragment } from './ui-fragment';

type Preview = {
  surface: string;
  title: string;
  text?: string;
  columns: string[];
  rows: { cells: string[]; note?: string }[];
  panel?: Fragment;
};

const NAV_ICONS: Record<string, LucideIcon> = {
  Overview: House,
  Cases: FolderOpen,
  'Human Tasks': UserCheck,
  Agents: Bot,
  Workflows: Route,
  Channels: Inbox,
  Skills: Sparkles,
  Guardrails: Shield,
  'Knowledge bases': Database,
  Tools: Wrench,
  Files: Folder,
  'Document types': FileText,
  Activity: List,
  Reviews: ListChecks,
  Access: ShieldCheck,
  Policies: Gavel,
  Settings,
};

const STATUS = /^(waiting|running|queued|overdue|failed|stuck|done|approved|rejected|published|draft|live|credited|declined|open|closed)$/i;
const toneOf = (v: string) =>
  /failed|stuck|rejected|declined|overdue/i.test(v) ? 'stop' : /done|approved|published|live|credited|closed/i.test(v) ? 'done' : 'step';

/**
 * A product screen as the reader will see it: the console's sidebar with the page's item selected, the page header,
 * its list, and an open panel. The screen is sized in em and its font follows the figure's width, so it scales as one
 * picture with no script, and server HTML, print and readers without JavaScript see all of it. Below 600px of figure
 * width the whole screen would be unreadable, so only the open panel shows (or the list when there is no panel), at
 * its natural size. Static markup only: no frames, no rotation, nothing that takes focus.
 *
 * Markdown: `<!-- site: preview caption="..." -->` above a list: `**Sidebar item · Page title**: one line`, then
 * `**Columns**: a, b, c`, one `**Row**: a, b, c` per row (a nested bullet pins a note to the row), and optionally
 * `**Panel · Title**: one line` with the annotated screen's nested rows.
 */
export function PreviewFigure({ data, caption }: { data: string; caption?: string }) {
  const p = JSON.parse(data) as Preview;
  const rowNotes = p.rows.filter((r) => r.note).map((r) => ({ label: r.cells[0], note: r.note! }));
  const rowPin = new Map(p.rows.filter((r) => r.note).map((r, i) => [r, i + 1]));
  const panel = p.panel && pinsFor(p.panel, rowNotes.length);
  const crop = p.panel && pinsFor(p.panel);
  const group = CONSOLE_NAV.find((g) => g.items.includes(p.surface))?.group;
  // The list as a fragment, for the phone view of a preview with no panel.
  const listFragment: Fragment = {
    surface: p.surface,
    title: p.title,
    text: p.text,
    fields: p.rows.map((r) => ({ label: r.cells[0], value: r.cells.slice(1).join(' · '), note: r.note })),
    actions: [],
  };
  const listPins = pinsFor(listFragment);
  return (
    <FigureFrame caption={caption}>
      <div className="ops-preview">
        <div className="ops-preview-wide">
          <div className="ops-preview-screen">
            <div className="ops-preview-side">
              {CONSOLE_NAV.map((g) => (
                <div key={g.group} className="ops-preview-group">
                  <p className="ops-preview-group-label">{g.group}</p>
                  {g.items.map((item) => {
                    const Icon = NAV_ICONS[item];
                    return (
                      <p key={item} className={`ops-preview-item${item === p.surface ? ' ops-preview-item-on' : ''}`}>
                        {Icon && <Icon aria-hidden strokeWidth={1.5} />}
                        {item}
                      </p>
                    );
                  })}
                </div>
              ))}
            </div>
            <div className="ops-preview-page">
              <p className="ops-preview-crumbs">
                {group} <span aria-hidden>›</span> {p.surface}
              </p>
              <p className="ops-preview-title">{p.title}</p>
              {p.text && <p className="ops-preview-text">{p.text}</p>}
              <div className={`ops-preview-body${p.panel ? ' ops-preview-body-split' : ''}`}>
                <table className="ops-preview-table">
                  <thead>
                    <tr>
                      {p.columns.map((c) => (
                        <th key={c} scope="col">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {p.rows.map((r, ri) => (
                      <tr key={ri} className={ri === 0 && p.panel ? 'ops-preview-row-on' : undefined}>
                        {r.cells.map((c, ci) => (
                          <td key={ci}>
                            {ci === 0 && rowPin.get(r) !== undefined && <Pin n={rowPin.get(r)!} />}
                            {STATUS.test(c) ? <span className={`ops-chip ops-chip-${toneOf(c)}`}>{c}</span> : c}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {p.panel && panel && (
                  <div className="ops-preview-panel">
                    <UiFragment fragment={p.panel} pins={panel.pins} />
                  </div>
                )}
              </div>
            </div>
          </div>
          <PinNotes notes={[...rowNotes, ...(panel?.notes ?? [])]} />
        </div>
        <div className="ops-preview-crop">
          {p.panel && crop ? (
            <>
              <UiFragment fragment={p.panel} pins={crop.pins} />
              <PinNotes notes={crop.notes} />
            </>
          ) : (
            <>
              <UiFragment fragment={listFragment} pins={listPins.pins} />
              <PinNotes notes={listPins.notes} />
            </>
          )}
        </div>
      </div>
    </FigureFrame>
  );
}

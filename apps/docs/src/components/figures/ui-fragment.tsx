import {
  BookOpen,
  Bot,
  Circle,
  FolderCheck,
  Inbox,
  type LucideIcon,
  Mail,
  Search,
  ServerCog,
  ShieldCheck,
  UserCheck,
  Users,
  Workflow,
} from 'lucide-react';

/** One field of a fragment: a label, its value, and the protection or note pinned to it, if any. */
export type FragmentField = { label: string; value: string; code?: string; note?: string };

/** A small piece of product screen drawn from markdown: which surface it is, what it shows, and its actions. */
export type Fragment = {
  surface: string;
  title: string;
  text?: string;
  fields: FragmentField[];
  actions: string[];
  actionsNote?: string;
};

// The surface word in a figure's markdown picks the icon, so authors never name an icon.
const ICONS: [RegExp, LucideIcon][] = [
  [/inbox|mailbox/i, Inbox],
  [/mail/i, Mail],
  [/workflow/i, Workflow],
  [/agent|chat/i, Bot],
  [/approv|task|review/i, UserCheck],
  [/case|record/i, FolderCheck],
  [/knowledge|handbook/i, BookOpen],
  [/lookup|search/i, Search],
  [/gateway|system/i, ServerCog],
  [/team|people/i, Users],
  [/polic|access/i, ShieldCheck],
];

export function surfaceIcon(surface: string): LucideIcon {
  return ICONS.find(([re]) => re.test(surface))?.[1] ?? Circle;
}

/**
 * A fragment of a product screen inside a figure: a window bar naming the surface, a title, its fields and its
 * buttons. It is a picture of a screen, so the buttons are text styled as buttons and take no focus. `pins` numbers
 * the fields that carry a note, matching the numbered list beside the figure.
 */
export function UiFragment({
  fragment,
  pins,
  size = 'sm',
  showTitle = true,
}: {
  fragment: Fragment;
  pins?: Map<FragmentField | 'actions', number>;
  size?: 'sm' | 'lg';
  /** Off where the figure already names the step beside the screen. */
  showTitle?: boolean;
}) {
  const actionsPin = pins?.get('actions');
  const Icon = surfaceIcon(fragment.surface);
  return (
    <div className={`ops-ui ops-ui-${size}`}>
      <div className="ops-ui-bar">
        <Icon aria-hidden className="ops-ui-icon" strokeWidth={1.5} />
        <span>{fragment.surface}</span>
      </div>
      <div className="ops-ui-body">
        {showTitle && <p className="ops-ui-title">{fragment.title}</p>}
        {fragment.text && <p className="ops-ui-text">{fragment.text}</p>}
        {fragment.fields.length > 0 && (
          <dl className="ops-ui-fields">
            {fragment.fields.map((f) => {
              const pin = pins?.get(f);
              return (
                <div key={f.label} className={`ops-ui-field${f.code ? ' ops-ui-field-code' : ''}`}>
                  <dt>
                    {pin !== undefined && (
                      <span className="ops-pin" aria-hidden>
                        {pin}
                      </span>
                    )}
                    {f.label}
                  </dt>
                  <dd>{f.code ? <pre className="ops-ui-code">{f.code}</pre> : f.value}</dd>
                </div>
              );
            })}
          </dl>
        )}
        {fragment.actions.length > 0 && (
          <div className="ops-ui-actions">
            {actionsPin !== undefined && (
              <span className="ops-pin" aria-hidden>
                {actionsPin}
              </span>
            )}
            {fragment.actions.map((a, i) => (
              <span key={a} className={`ops-ui-btn${i === 0 ? ' ops-ui-btn-primary' : ''}`}>
                {a}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

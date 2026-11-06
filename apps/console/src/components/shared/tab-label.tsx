import * as React from 'react';

/**
 * A tab's label with its title in the tab's own colour and what follows the first " · " (a count or a status, such as
 * "Tools · 6 of 15 on") muted, in the active tab and the others alike. A label that is not text is shown as given.
 */
export function TabLabel({ label }: { label: React.ReactNode }) {
  if (typeof label !== 'string') return <>{label}</>;
  const at = label.indexOf(' · ');
  if (at < 0) return <>{label}</>;
  // One span, so a trigger that spaces its children (an icon and its label) does not split the label.
  return (
    <span>
      {label.slice(0, at)}
      <span className="text-muted-foreground">{label.slice(at)}</span>
    </span>
  );
}

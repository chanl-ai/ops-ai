import * as React from 'react';

/**
 * Renders the small markdown subset agents reply with: paragraphs, bullet and numbered lists, **bold** and
 * citation markers ([1] or [^1]). A full markdown library is not needed for that and would add a dependency.
 */
export function RichText({ text, renderCitation, streaming }: { text: string; renderCitation: (n: number) => React.ReactNode; streaming?: boolean }) {
  // A marker cut off mid-stream ("[^", "[1") is hidden until it completes.
  const src = streaming ? text.replace(/\s*\[\^?\d*$/, '') : text;
  const blocks = src.split(/\n{2,}/).filter((b) => b.trim());

  const inline = (s: string, key: string) =>
    s.split(/(\*\*[^*]+\*\*|\s?\[\^?\d+\])/g).map((part, i) => {
      const k = `${key}-${i}`;
      const cite = part.match(/^\s?\[\^?(\d+)\]$/);
      if (cite) return <React.Fragment key={k}>{renderCitation(Number(cite[1]))}</React.Fragment>;
      if (part.startsWith('**') && part.endsWith('**')) return <strong key={k} className="font-semibold">{part.slice(2, -2)}</strong>;
      return <React.Fragment key={k}>{part}</React.Fragment>;
    });

  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((b, bi) => {
        const lines = b.split('\n');
        if (lines.every((l) => /^\s*[-*] /.test(l)))
          return (
            <ul key={bi} className="list-disc space-y-1 pl-5">
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*[-*] /, ''), `${bi}-${li}`)}</li>
              ))}
            </ul>
          );
        if (lines.every((l) => /^\s*\d+\. /.test(l)))
          return (
            <ol key={bi} className="list-decimal space-y-1 pl-5">
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*\d+\. /, ''), `${bi}-${li}`)}</li>
              ))}
            </ol>
          );
        return (
          <p key={bi} className="whitespace-pre-wrap">
            {inline(b, String(bi))}
          </p>
        );
      })}
    </div>
  );
}

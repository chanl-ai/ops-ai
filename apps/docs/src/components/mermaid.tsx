import { renderMermaidSVG } from 'beautiful-mermaid';

/**
 * A Mermaid diagram drawn at build time. Its colours are CSS variables (global.css, .ops-mermaid), so one SVG follows
 * the light and dark theme without a second render; it keeps its drawn size and scrolls when wider than the page.
 */
export function OpsMermaid({ chart, caption }: { chart: string; caption?: string }) {
  let svg: string;
  try {
    svg = renderMermaidSVG(chart, {
      bg: 'var(--ops-mm-bg)',
      fg: 'var(--ops-mm-fg)',
      line: 'var(--ops-mm-line)',
      accent: 'var(--ops-mm-accent)',
      muted: 'var(--ops-mm-muted)',
      surface: 'var(--ops-mm-surface)',
      border: 'var(--ops-mm-border)',
      font: 'var(--ops-font)',
      transparent: true,
    });
  } catch (err) {
    // A diagram that cannot render fails the build rather than shipping an empty figure.
    throw new Error(`a Mermaid diagram failed to render: ${(err as Error).message}\n${chart}`);
  }
  // On a narrow page the drawing shrinks to the frame, but never below 80% of its drawn size (13px labels stay about
  // 10px or more); a wider drawing scrolls instead.
  const drawn = Number(svg.match(/<svg[^>]*\swidth="([\d.]+)"/)?.[1]);
  if (drawn) svg = svg.replace(/<svg([^>]*)\sstyle="/, `<svg$1 style="min-width:${Math.round(drawn * 0.8)}px;`);
  return (
    <figure className="ops-figure ops-mermaid not-prose">
      {/* The caption doubles as the accessible name: the drawing itself carries no alt text. */}
      <div
        className="ops-figure-media"
        role={caption ? 'img' : undefined}
        aria-label={caption}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

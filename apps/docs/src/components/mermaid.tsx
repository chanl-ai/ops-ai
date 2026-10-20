import { renderMermaidSVG } from 'beautiful-mermaid';

/**
 * A Mermaid diagram drawn at build time. Its colours are CSS variables (global.css, .ops-mermaid), so one SVG follows
 * the light and dark theme without a second render; it keeps its drawn size and scrolls when wider than the page.
 */
export function OpsMermaid({ chart }: { chart: string }) {
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
  return (
    <figure className="ops-figure ops-mermaid not-prose">
      <div className="ops-figure-media" dangerouslySetInnerHTML={{ __html: svg }} />
    </figure>
  );
}

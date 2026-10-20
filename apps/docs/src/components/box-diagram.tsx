import fs from 'node:fs';
import path from 'node:path';

import yaml from 'js-yaml';

import { DIAGRAM_CSS, renderBoxDiagram } from '@/lib/box-diagram.mjs';
import { repoIndex } from '@/lib/repo.mjs';

/**
 * The live architecture diagram for docs/diagrams/<name>.yaml: the drawing in the exported SVG, themed by the site
 * and with each box that names a page linking to it.
 */
export function BoxDiagram({ name, caption }: { name: string; caption?: string }) {
  const { root, pages } = repoIndex();
  const data = yaml.load(fs.readFileSync(path.join(root, 'docs/diagrams', `${name}.yaml`), 'utf8')) as object;
  const svg = renderBoxDiagram(data, {
    linkHref: (href: string) => {
      const page = pages[`docs/${href}`];
      if (!page) throw new Error(`docs/diagrams/${name}.yaml links ${href}, which is not a docs page`);
      return `/docs${page.url}`;
    },
  });
  return (
    <figure className="ops-figure ops-diagram not-prose">
      {/* The same rules the exported SVG embeds; the colours come from the site theme (global.css, --d-*). */}
      <style dangerouslySetInnerHTML={{ __html: DIAGRAM_CSS }} />
      <div className="ops-figure-media" dangerouslySetInnerHTML={{ __html: svg }} />
      {caption && <figcaption>{caption}</figcaption>}
    </figure>
  );
}

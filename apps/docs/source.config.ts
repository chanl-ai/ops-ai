import { defineConfig, defineDocs, frontmatterSchema } from 'fumadocs-mdx/config';
import { z } from 'zod';

import { remarkOpsAi } from './src/lib/remark-ops-ai.mjs';

// The docs are ops-ai's own markdown in ../../docs, read in place. They carry no frontmatter: the title comes from
// each page's first heading (remarkOpsAi moves it into the frontmatter).
export const docs = defineDocs({
  dir: '../../docs',
  docs: {
    files: ['**/*.md', '!plan/**', '!media/**', '!**/node_modules/**'],
    schema: frontmatterSchema.extend({ title: z.string().optional() }),
  },
  meta: { files: [] },
});

export default defineConfig({
  mdxOptions: {
    // remarkOpsAi runs before Fumadocs' defaults, so it wraps images before remarkImage turns them into imports.
    // In dev a broken link warns instead of throwing: turbopack caches a loader's result by the page's own content, so
    // a throw caused by another page's edit stays cached across restarts and every route answers 500 until .next is
    // deleted. The build still throws, and so does `pnpm check:links`.
    remarkPlugins: (defaults) => [
      [remarkOpsAi, process.env.NODE_ENV === 'development' ? { throwOnError: false, warn: true } : {}],
      ...defaults,
    ],
  },
});

import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import type { ReactNode } from 'react';

import { Brand } from '@/components/brand';
import { RailSections, RailTocProvider } from '@/components/rail';
import { source } from '@/lib/source';

// Inside the [[...slug]] segment, so it renders per page and can put that page's sections in the rail.
export default async function Layout({ children, params }: { children: ReactNode; params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  const page = source.getPage(slug);
  const toc = page?.data.toc ?? [];
  return (
    <RailTocProvider toc={toc}>
      <DocsLayout
        tree={source.pageTree}
        nav={{ title: <Brand />, url: '/' }}
        githubUrl="https://github.com/chanl-ai/ops-ai"
        sidebar={{ collapsible: false, banner: <RailSections key="rail-sections" /> }}
      >
        {children}
      </DocsLayout>
    </RailTocProvider>
  );
}

import { DocsLayout } from 'fumadocs-ui/layouts/notebook';
import type { ReactNode } from 'react';

import { Brand } from '@/components/brand';
import { sidebarTabs, sidebarTree } from '@/lib/source';

// The four tabs sit in the top bar and the sidebar shows only the open tab's groups; the page's own contents are on
// the right, so the left holds navigation alone.
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout
      tree={sidebarTree}
      tabMode="navbar"
      tabs={sidebarTabs}
      nav={{ title: <Brand />, url: '/', mode: 'top' }}
      githubUrl="https://github.com/chanl-ai/ops-ai"
      sidebar={{ collapsible: false }}
    >
      {children}
    </DocsLayout>
  );
}

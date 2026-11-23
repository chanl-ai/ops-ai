import type { ReactNode } from 'react';

import { AgentPageRoot } from './_parts/agent-page';

/**
 * One layout holds the agent page for every tab, so the draft and the test chat survive a move between tabs. The tab
 * pages draw nothing, but `children` is rendered: without it the bare address's redirect (an older `?tab=` link) never
 * runs and the page opens on Settings.
 */
export default function AgentLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <AgentPageRoot />
    </>
  );
}

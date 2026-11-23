import type { ReactNode } from 'react';

import { SkillPageRoot } from './_parts/skill-page';

/**
 * One layout holds the skill page for every tab, so unsaved text survives a move between Instructions and Settings.
 * The tab pages draw nothing; `children` is rendered so a redirect a page makes still runs.
 */
export default function SkillLayout({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <SkillPageRoot />
    </>
  );
}

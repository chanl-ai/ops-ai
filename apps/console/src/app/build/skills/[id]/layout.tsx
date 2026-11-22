import { SkillPageRoot } from './_parts/skill-page';

/** One layout holds the skill page for every tab, so unsaved text survives a move between Instructions and Settings. */
export default function SkillLayout() {
  return <SkillPageRoot />;
}

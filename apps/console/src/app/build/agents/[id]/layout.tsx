import { AgentPageRoot } from './_parts/agent-page';

/** One layout holds the agent page for every tab, so the draft and the test chat survive a move between tabs. */
export default function AgentLayout() {
  return <AgentPageRoot />;
}

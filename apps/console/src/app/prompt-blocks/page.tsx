import { redirect } from 'next/navigation';

/** Prompt blocks became always-on skills (spec 11 4.1); old links land on that view. */
export default function PromptBlocksPage() {
  redirect('/skills?view=always');
}

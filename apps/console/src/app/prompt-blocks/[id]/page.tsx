import { redirect } from 'next/navigation';

/** Block ids from before blocks became always-on skills, and the skill each became. Unknown ids land on the view. */
const SKILL_FOR_BLOCK: Record<string, string> = {
  pb_disclosure: 'sk_bank_disclosure',
  pb_tone: 'sk_plain_tone',
  pb_collections: 'sk_collections_disclosure',
  pb_citation: 'sk_citation_rule',
  pb_pii: 'sk_pii_handling',
  pb_email_format: 'sk_email_format',
};

export default async function PromptBlockPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const skill = SKILL_FOR_BLOCK[id];
  redirect(skill ? `/skills/${skill}` : '/skills?view=always');
}

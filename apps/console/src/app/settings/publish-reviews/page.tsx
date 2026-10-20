import { redirect } from 'next/navigation';

/** Publish reviews moved under Policies in the settings tree (c-214); this path stays for old links. */
export default function PublishReviewsRedirect() {
  redirect('/settings/policies/publish-reviews');
}

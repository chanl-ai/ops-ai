import { redirect } from 'next/navigation';

/** Members are managed on Access (c-077); this path stays for old links and the Settings menu. */
export default function MembersPage() {
  redirect('/access');
}

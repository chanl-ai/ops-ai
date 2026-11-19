import { redirect } from 'next/navigation';

/** Members are managed on Access; this path stays for old links and the Settings menu. */
export default function MembersPage() {
  redirect('/govern/access');
}

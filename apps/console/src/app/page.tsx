import { redirect } from 'next/navigation';

/** The console opens on Chat; the Overview lives at /overview. */
export default function Home() {
  redirect('/chat');
}

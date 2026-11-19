'use client';

import { usePathname } from 'next/navigation';

import { useFlagState } from '@/hooks/flag-queries';

import { ChatListColumn } from './_parts/chat-list-column';
import { chatListPlace } from './_parts/chat-list';

/**
 * The chat pages: with the one sidebar (area tabs off) the person's chats sit in a column beside the conversation; with
 * area tabs on they stay in the main sidebar and this adds nothing. All chats is a table page and gets no column.
 */
export default function ChatSectionLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const place = chatListPlace(useFlagState('area_tabs'), pathname);
  if (place !== 'column') return <>{children}</>;
  return (
    <div className="flex min-w-0">
      <ChatListColumn />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

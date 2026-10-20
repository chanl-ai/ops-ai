'use client';

import { useParams } from 'next/navigation';

import { ChatWorkspace } from '../_parts/chat-workspace';

export default function ChatThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  return <ChatWorkspace threadId={threadId} />;
}

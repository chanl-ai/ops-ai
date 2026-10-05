'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Bell, ChartColumn, KeyRound, Settings, Users, Webhook, type LucideIcon } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { cn } from '@/lib/utils';

export const SETTINGS_NAV: { id: string; title: string; href: string; icon: LucideIcon; description: string }[] = [
  { id: 'members', title: 'Members and roles', href: '/settings/members', icon: Users, description: 'Who is in the team and what they can do' },
  { id: 'notifications', title: 'Notifications', href: '/settings/notifications', icon: Bell, description: 'Where approvals, SLA warnings and alerts go' },
  { id: 'webhooks', title: 'Webhooks', href: '/settings/webhooks', icon: Webhook, description: 'Send events to the bank’s other systems' },
  { id: 'api-keys', title: 'API keys', href: '/settings/api-keys', icon: KeyRound, description: 'Keys for systems that start runs or read logs' },
  { id: 'usage', title: 'Usage and cost', href: '/settings/usage', icon: ChartColumn, description: 'Tokens, model cost and tool calls for chargeback' },
];

/** Left settings navigation, adapted from the shared component library's settings navigation: a rail on wide screens, a scroller on narrow ones. */
function SettingsNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Settings" className="flex gap-1 overflow-x-auto pb-2 lg:w-56 lg:shrink-0 lg:flex-col lg:self-start lg:overflow-x-visible lg:pb-0 lg:sticky lg:top-0">
      {SETTINGS_NAV.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.id}
            href={item.href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'relative flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
              active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-primary/10 hover:text-primary',
            )}
          >
            <item.icon className="size-4 shrink-0" />
            {item.title}
            {active && <span aria-hidden="true" className="absolute inset-y-1.5 right-0 hidden w-1 rounded-full bg-primary lg:block" />}
          </Link>
        );
      })}
    </nav>
  );
}

/** Settings shell: one page header, the settings rail, then the section with its own title and actions. */
export function SettingsPageLayout({ section, description, actions, children }: { section?: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <PageLayout icon={Settings} title="Settings" description="Members, notifications, integrations and usage for the current team">
      <div className="flex flex-col gap-6 lg:flex-row">
        <SettingsNav />
        <div className="flex min-w-0 flex-1 flex-col gap-4">
          {section && (
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold">{section}</h2>
                {description && <p className="text-sm text-muted-foreground">{description}</p>}
              </div>
              {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
            </div>
          )}
          {children}
        </div>
      </div>
    </PageLayout>
  );
}

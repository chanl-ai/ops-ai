import { Suspense } from 'react';
import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';

import { AppSidebar } from '@/components/app-sidebar';
import { ClientGate } from '@/components/client-gate';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { SiteHeader } from '@/components/site-header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';

import { HeaderNotifications } from './_shell/header-notifications';
import { HeaderSearch } from './_shell/header-search';
import { Providers } from './providers';

import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-jetbrains' });

export const metadata: Metadata = {
  title: 'Ops AI',
  description: 'Operations console for AI agents, workflows and human review',
};

/** Shell follows the shared component library's dashboard layout: inset sidebar, fixed header, one scrolling content column. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${mono.variable} font-sans`}>
        <Providers>
          <SidebarProvider
            style={
              {
                '--header-height': 'calc(var(--spacing) * 14)',
                '--sidebar-width': '14rem',
              } as React.CSSProperties
            }
          >
            <AppSidebar variant="inset" />
            <SidebarInset className="h-[calc(100svh-1rem)] min-w-0 overflow-hidden">
              <SiteHeader
                actions={
                  <>
                    <HeaderSearch />
                    <HeaderNotifications />
                  </>
                }
              />
              <div className="@container/main flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto">
                <Suspense>
                  <ClientGate
                    fallback={
                      <div className="px-6 py-6 lg:px-8">
                        <PageSkeleton statCards={4} tableRows={6} />
                      </div>
                    }
                  >{children}</ClientGate>
                </Suspense>
              </div>
            </SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  );
}

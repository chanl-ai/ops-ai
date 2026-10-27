import type { Metadata } from 'next';
import localFont from 'next/font/local';

import { AppShell } from './_shell/app-shell';
import { Providers } from './providers';

import './globals.css';

// Served from npm packages, not fetched from Google Fonts at build, so a build behind a package mirror reaches nothing else.
const inter = localFont({ src: '../../node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2', variable: '--font-inter', weight: '100 900' });
const mono = localFont({ src: '../../node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2', variable: '--font-jetbrains', weight: '100 800' });

export const metadata: Metadata = {
  title: 'Ops AI',
  description: 'Operations console for AI agents, workflows and human review',
};

/** Fonts and providers; AppShell adds the dashboard shell (inset sidebar, fixed header) and the sign-in guard. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${mono.variable} font-sans`}>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}

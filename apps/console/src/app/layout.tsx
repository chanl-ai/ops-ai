import type { Metadata } from 'next';
import localFont from 'next/font/local';

import { brandColours } from '@/lib/api';
import { brandStyle } from '@/lib/brand';

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

const FOLLOW_SYSTEM_THEME = `(function(){try{var m=window.matchMedia('(prefers-color-scheme: dark)');var set=function(){document.documentElement.classList.toggle('dark',m.matches)};set();m.addEventListener('change',set)}catch(e){}})();`;

// A demo's accent colour from .env (OPS_BRAND_PRIMARY), read when the server starts.
const BRAND = brandStyle(brandColours);

/** Fonts and providers; AppShell adds the dashboard shell (inset sidebar, fixed header) and the sign-in guard. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* The console follows the system's light or dark setting, before the first paint and as it changes; there is
            no switch of its own. */}
        <script dangerouslySetInnerHTML={{ __html: FOLLOW_SYSTEM_THEME }} />
        {BRAND && <style dangerouslySetInnerHTML={{ __html: BRAND }} />}
      </head>
      <body className={`${inter.variable} ${mono.variable} font-sans`}>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}

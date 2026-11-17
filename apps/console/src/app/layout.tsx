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

// Sets the `dark` class before the first paint from the saved choice (next-themes' storage key `theme`: light, dark or
// system) and follows the OS while the choice is system. ThemeProvider's own script is switched off in providers.tsx:
// React 19 refuses a script rendered by a client component.
const APPLY_THEME = `(function(){try{var d=document.documentElement,m=window.matchMedia('(prefers-color-scheme: dark)');var set=function(){var t=localStorage.getItem('theme');var dark=t==='dark'||(t!=='light'&&m.matches);d.classList.toggle('dark',dark);d.style.colorScheme=dark?'dark':'light'};set();m.addEventListener('change',set)}catch(e){}})();`;

// A demo's accent colour from .env (OPS_BRAND_PRIMARY), read when the server starts.
const BRAND = brandStyle(brandColours);

/** Fonts and providers; AppShell adds the dashboard shell (inset sidebar, fixed header) and the sign-in guard. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: APPLY_THEME }} />
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

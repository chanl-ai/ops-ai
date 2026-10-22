import './global.css';

import { RootProvider } from 'fumadocs-ui/provider/next';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { BRAND } from '@/components/brand';

// The console's Feedback button; the two apps share no package, so docs imports the console's file.
import { UiFeedback } from '../../../console/src/components/shared/ui-feedback';

import logo from '../../../../docs/media/logo-light.svg';

export const metadata: Metadata = {
  title: { default: BRAND, template: `%s | ${BRAND}` },
  description: 'Ops AI: agents and workflows for regulated operations teams, with a person approving every change.',
  icons: { icon: logo.src },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        {/* Search reads the index built ahead, from under the /docs base path. */}
        <RootProvider search={{ options: { type: 'static', api: '/docs/api/search' } }}>{children}</RootProvider>
        <UiFeedback enabled={process.env.NEXT_PUBLIC_UI_FEEDBACK} />
      </body>
    </html>
  );
}

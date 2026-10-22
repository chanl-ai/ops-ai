'use client';

import { useEffect } from 'react';

/** The collector a developer runs on their own machine (the ui-feedback skill); it serves the widget. */
const WIDGET = 'http://127.0.0.1:4790/widget.js';

/**
 * The Feedback button in development: loads the widget from the developer's own collector, so comments pinned on a
 * page reach the agent working on it. `enabled` is the app's NEXT_PUBLIC_UI_FEEDBACK, which `make up` sets to `1` only
 * when the collector answers. A production build never loads it, whatever the flag says. A failed load stays silent.
 *
 * Shared by the console and the docs site, which imports this file. It imports only react: the two apps resolve
 * different copies of next, so next/script from here would put a second Next into the docs bundle.
 */
export function UiFeedback({ enabled }: { enabled: string | undefined }) {
  useEffect(() => {
    if (process.env.NODE_ENV === 'production' || enabled !== '1') return;
    if (document.querySelector(`script[src="${WIDGET}"]`)) return;
    const script = document.createElement('script');
    script.src = WIDGET;
    script.async = true;
    script.onerror = () => {
      console.debug('[ui-feedback] no collector on 127.0.0.1:4790');
      script.remove();
    };
    document.body.appendChild(script);
  }, [enabled]);
  return null;
}

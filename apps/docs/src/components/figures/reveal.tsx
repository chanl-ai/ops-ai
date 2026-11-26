'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/**
 * Reveals a figure's parts once, in order, the first time it scrolls into view. The parts are visible in the server
 * HTML; only after hydration does the figure hide them for the reveal, so print, search and readers without
 * JavaScript always see the whole figure. The motion itself is CSS (global.css, .ops-reveal).
 */
export function Reveal({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    // Already on screen at load: show it as it is, with no reveal.
    if (el.getBoundingClientRect().top < window.innerHeight * 0.85) return;
    el.dataset.reveal = 'waiting';
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        el.dataset.reveal = 'in';
        io.disconnect();
      },
      { rootMargin: '0px 0px -15% 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`ops-reveal ${className ?? ''}`}>
      {children}
    </div>
  );
}

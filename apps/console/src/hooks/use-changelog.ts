'use client';

import * as React from 'react';

import { buildCommit, buildTag, changelogSource, roadmapSource, uiFeedback } from '@/lib/api';
import { type ChangelogEntry, hasUnseen, parseChangelog, parseRoadmap } from '@/lib/changelog';
import { versionLabel } from '@/lib/version';

const SEEN_KEY = 'ops-whats-new-seen';
const VERSION = versionLabel(buildTag, buildCommit);
// The dev-only Feedback button (ui-feedback widget.js) loads in development when the collector answers.
const FEEDBACK_ON = process.env.NODE_ENV !== 'production' && uiFeedback === '1';

function readSeen(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SEEN_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.map(String) : [];
  } catch {
    return [];
  }
}

/**
 * What's new and Coming next as built (c-510), the build's version, whether the dev Feedback button shares the corner,
 * and whether this person has an entry they have not opened. Seen ids are kept in this browser; with storage blocked
 * the dot shows on every load and opening still works.
 */
export function useChangelog() {
  const entries = React.useMemo<ChangelogEntry[]>(() => parseChangelog(changelogSource), []);
  const roadmap = React.useMemo(() => parseRoadmap(roadmapSource), []);
  // Read after mount: the server render has no storage, and a dot that appears on hydration would mismatch.
  const [unseen, setUnseen] = React.useState(false);
  React.useEffect(() => {
    setUnseen(hasUnseen(entries, readSeen()));
  }, [entries]);
  const markSeen = React.useCallback(() => {
    setUnseen(false);
    try {
      localStorage.setItem(SEEN_KEY, JSON.stringify(entries.map((e) => e.id)));
    } catch {
      // Storage blocked: the dot comes back next load, which is the honest answer.
    }
  }, [entries]);
  return { entries, roadmap, unseen, markSeen, version: VERSION, feedbackOn: FEEDBACK_ON };
}

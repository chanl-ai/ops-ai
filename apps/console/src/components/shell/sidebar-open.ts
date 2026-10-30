// Whether the person left the app sidebar open, kept in this browser (c-552). Written only for the person's own toggles:
// pages that fold the sidebar for room (components/shared/collapsed-sidebar.ts) also write the sidebar's cookie, so the
// cookie cannot say what the person chose.
const KEY = 'ops.sidebar.open';

export function readSidebarOpen(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== 'false';
  } catch {
    return true;
  }
}

export function writeSidebarOpen(open: boolean) {
  try {
    window.localStorage.setItem(KEY, String(open));
  } catch {
    // Not remembered; the sidebar opens on the next load.
  }
}

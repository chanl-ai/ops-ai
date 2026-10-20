// Seed times are relative to page load; the mock only runs in the browser.
export const NOW = new Date()

export function ago(hours: number): string {
  return new Date(NOW.getTime() - hours * 3600_000).toISOString()
}

export function daysAgo(days: number): string {
  return ago(days * 24)
}

export function inDays(days: number): string {
  return new Date(NOW.getTime() + days * 86400_000).toISOString()
}

export function inHours(hours: number): string {
  return new Date(NOW.getTime() + hours * 3600_000).toISOString()
}

export function dateOnly(daysAgoN: number): string {
  return daysAgo(daysAgoN).slice(0, 10)
}

// Small deterministic PRNG so generated lists are stable between renders.
export function seeded(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 0xffffffff
  }
}

/** A stream went quiet past its limit without closing. */
export class IdleTimeout extends Error {
  ms: number;
  constructor(ms: number) {
    super(`No reply for ${Math.round(ms / 1000)} seconds.`);
    this.name = 'IdleTimeout';
    this.ms = ms;
  }
}

/**
 * Yields each event of `source`, and throws IdleTimeout when the next one takes longer than `ms`. The limit restarts
 * with every event, so a long answer that keeps streaming is never cut off; only silence is.
 */
export async function* withIdleTimeout<T>(source: AsyncIterable<T>, ms: number): AsyncIterable<T> {
  const it = source[Symbol.asyncIterator]();
  for (;;) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const idle = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new IdleTimeout(ms)), ms);
    });
    try {
      const next = await Promise.race([it.next(), idle]);
      if (next.done) return;
      yield next.value;
    } finally {
      clearTimeout(timer);
    }
  }
}

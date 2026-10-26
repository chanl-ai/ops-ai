/**
 * The one place a call goes out: the base URL per service, the key and team headers, the `{success, data}` envelope,
 * typed errors and retries. The raw operations and the resource modules call through it.
 */
import { errorFor } from './errors.js';

export type Service = 'platform' | 'agents' | 'tools' | 'kb' | 'files' | 'documents';

export interface Operation {
  readonly method: string;
  readonly path: string;
  readonly pathParams: readonly string[];
  readonly query: readonly string[];
  readonly headers: readonly string[];
  readonly body: string | null;
  readonly stream: boolean;
}

export interface Config {
  /** The origin every service is reached through, under /api/<service>. */
  baseUrl: string;
  apiKey?: string;
  /** A person's session token from `OpsAI.signIn`, sent as a Bearer token. */
  accessToken?: string;
  team?: string;
  /** A service reached at its own address instead, e.g. `{ agents: 'http://localhost:8700' }`. */
  services?: Partial<Record<Service, string>>;
  timeoutMs?: number;
  maxRetries?: number;
  fetch?: typeof fetch;
}

export interface CallArgs {
  path?: Record<string, unknown>;
  query?: Record<string, unknown>;
  headers?: Record<string, unknown>;
  body?: unknown;
}

export interface ServerEvent {
  event?: string;
  id?: string;
  data: unknown;
}

const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);
const IDEMPOTENCY = 'Idempotency-Key';

export class Transport {
  readonly config: Required<Pick<Config, 'baseUrl' | 'timeoutMs' | 'maxRetries'>> & Config;
  private readonly fetch: typeof fetch;

  constructor(config: Config) {
    this.config = { timeoutMs: 30_000, maxRetries: 2, ...config };
    this.fetch = config.fetch ?? globalThis.fetch.bind(globalThis);
  }

  headers(extra: Record<string, unknown> = {}): Record<string, string> {
    const h: Record<string, string> = { Accept: 'application/json', 'User-Agent': 'ops-ai-typescript' };
    if (this.config.apiKey) h['X-Api-Key'] = this.config.apiKey;
    else if (this.config.accessToken) h.Authorization = `Bearer ${this.config.accessToken}`;
    if (this.config.team) h['X-Team-Id'] = this.config.team;
    for (const [k, v] of Object.entries(extra)) if (v !== undefined && v !== null) h[k] = String(v);
    return h;
  }

  url(service: Service, op: Operation, path: Record<string, unknown> = {}, query: Record<string, unknown> = {}): string {
    const base = this.config.services?.[service] ?? `${this.config.baseUrl.replace(/\/$/, '')}/api/${service}`;
    let route = op.path;
    for (const name of op.pathParams) {
      const value = path[name];
      if (value === undefined || value === null) throw new TypeError(`${name} is required`);
      route = route.replace(`{${name}}`, encodeURIComponent(String(value)));
    }
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null) continue;
      for (const item of Array.isArray(v) ? v : [v]) qs.append(k, String(item));
    }
    const q = qs.toString();
    return `${base.replace(/\/$/, '')}${route}${q ? `?${q}` : ''}`;
  }

  async call(service: Service, op: Operation, args: CallArgs = {}): Promise<unknown> {
    if (op.stream) return this.stream(service, op, args);
    const headers = this.headers(args.headers);
    const init: RequestInit = { method: op.method, headers };
    if (args.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(args.body);
    }
    // Reads, and writes whose route takes an idempotency key and got one: a retried write without one could run twice.
    const retryable = op.method === 'GET' || (op.headers.includes(IDEMPOTENCY) && Boolean(headers[IDEMPOTENCY]));
    const attempts = retryable ? this.config.maxRetries + 1 : 1;
    const url = this.url(service, op, args.path, args.query);
    for (let attempt = 0; ; attempt++) {
      let response: Response;
      try {
        response = await this.fetch(url, { ...init, signal: AbortSignal.timeout(this.config.timeoutMs) });
      } catch (e) {
        if (attempt + 1 >= attempts) throw e;
        await sleep(backoff(attempt));
        continue;
      }
      if (RETRY_STATUS.has(response.status) && attempt + 1 < attempts) {
        await sleep(backoff(attempt));
        continue;
      }
      return result(response);
    }
  }

  async *stream(service: Service, op: Operation, args: CallArgs = {}): AsyncGenerator<ServerEvent> {
    const headers = { ...this.headers(args.headers), Accept: 'text/event-stream' };
    const response = await this.fetch(this.url(service, op, args.path, args.query), { method: op.method, headers });
    if (!response.ok || !response.body) {
      await result(response);
      return;
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    let event: Partial<ServerEvent> = {};
    let data: string[] = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      let nl: number;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, '');
        buffer = buffer.slice(nl + 1);
        if (line === '') {
          if (data.length) yield { ...event, data: parse(data.join('\n')) };
          event = {};
          data = [];
        } else if (!line.startsWith(':')) {
          const i = line.indexOf(':');
          const key = i < 0 ? line : line.slice(0, i);
          const val = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '');
          if (key === 'data') data.push(val);
          else if (key === 'event' || key === 'id') event[key] = val;
        }
      }
    }
    if (data.length) yield { ...event, data: parse(data.join('\n')) };
  }
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function result(response: Response): Promise<unknown> {
  const text = await response.text();
  const payload = text ? parse(text) : null;
  const obj = payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined;
  if (!response.ok || obj?.success === false) {
    const err = (obj?.error as Record<string, unknown> | undefined) ?? {};
    throw errorFor(response.status, err, response.headers.get('x-request-id') ?? undefined, text.slice(0, 500));
  }
  if (obj && 'success' in obj && 'data' in obj) return obj.data;
  return payload;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const backoff = (attempt: number) => Math.min(8000, 500 * 2 ** attempt) * (0.5 + Math.random() / 2);

/** A list response's items and how to ask for the next page, for both paging shapes the API uses. */
export function pageItems(data: unknown): [unknown[], Record<string, unknown> | null] {
  if (Array.isArray(data)) return [data, null];
  if (!data || typeof data !== 'object') return [[], null];
  const d = data as Record<string, unknown>;
  const items = (d.items as unknown[] | undefined) ?? (Array.isArray(d.data) ? (d.data as unknown[]) : []);
  const pagination = d.pagination as Record<string, unknown> | undefined;
  if (pagination?.hasNext) return [items, { page: Number(pagination.page ?? 1) + 1 }];
  if (d.nextCursor) return [items, { cursor: d.nextCursor }];
  return [items, null];
}

import type { ModelProvider, ProviderHealth, ProviderInput } from '@/lib/types/models';

const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();

/** The shared stack's providers as they would read once keys move to Secrets: OpenAI answering, Anthropic named but
 * its key never added. Sample data for the c-177 design gate; nothing here calls a service. */
export const PROVIDERS: ModelProvider[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    type: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    keySecret: 'OPENAI_API_KEY',
    keySet: true,
    health: { status: 'ok', at: minutesAgo(6), latencyMs: 231, models: 64 },
    aliases: ['default', 'gpt-5.5', 'guardrail-check', 'memory-extract'],
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    type: 'anthropic',
    baseUrl: 'https://api.anthropic.com/v1',
    keySecret: 'ANTHROPIC_API_KEY',
    keySet: false,
    health: { status: 'untested', at: null },
    aliases: [],
  },
  {
    id: 'bank-llm',
    name: 'Harbor & Pine private model',
    type: 'openai_compatible',
    baseUrl: 'https://llm.harborpine.internal/v1',
    keySecret: 'HARBORPINE_LLM_KEY',
    keySet: true,
    health: { status: 'failed', at: minutesAgo(42), error: '401 invalid api key' },
    aliases: ['reasoning'],
  },
];

/** What a test would answer: a key with the provider's prefix connects, anything else is refused. */
export function sampleTest(input: ProviderInput, stored: boolean): ProviderHealth {
  const prefix = input.type === 'anthropic' ? 'sk-ant-' : input.type === 'openai' ? 'sk-' : '';
  const ok = input.key ? input.key.startsWith(prefix) : stored;
  return ok
    ? { status: 'ok', at: new Date().toISOString(), latencyMs: 180 + Math.round(Math.random() * 120), models: input.type === 'anthropic' ? 9 : 64 }
    : { status: 'failed', at: new Date().toISOString(), error: '401 invalid api key' };
}

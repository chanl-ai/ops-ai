/** The agents of the caller's team citing one knowledge base, from agents-service's `GET /v1/knowledge-usage`. */
export interface KnowledgeUsage {
  kbId: string;
  agents: { id: string; name: string }[];
  /** Agents of other teams citing it, counted only. */
  elsewhere: number;
}

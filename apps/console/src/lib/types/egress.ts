import type { ModuleRef } from './tool-modules';

/** A host tool calls may reach (tools-service GET /v1/egress). `modules` are the tool sets whose endpoint is on it. */
export interface ListedHost {
  host: string;
  note: string;
  addedBy: string;
  addedAt: string;
  modules: ModuleRef[];
}

/** A private range a listed host may resolve into; loopback, link-local and cloud metadata are never listable. */
export interface ListedRange {
  cidr: string;
  note: string;
  addedBy: string;
  addedAt: string;
}

export interface AllowList {
  hosts: ListedHost[];
  ranges: ListedRange[];
}

export type EgressKind = 'host' | 'range';

/** `changed` is false when the value was already listed. */
export interface EgressChange {
  kind: EgressKind;
  value: string;
  changed: boolean;
}

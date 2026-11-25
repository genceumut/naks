// Type declarations for naks-client.mjs (TypeScript projects).

export declare const PROTOCOL_VERSION: 1;

export declare class NaksPending extends Error {
  ids: string[];
  naksDir: string;
  constructor(ids: string[], naksDir: string);
}

export interface NaksOptions {
  system?: string | null;
  schema?: unknown;
  inputs?: unknown;
  task?: string;
  format?: "text" | "markdown" | "json" | null;
  /** image (png/jpg/gif/webp) or PDF paths */
  files?: string[];
  /** seconds to poll for a response before throwing NaksPending */
  wait?: number;
}

export declare function submit(prompt: string, opts?: Omit<NaksOptions, "wait">): string;
export declare function get<T = any>(id: string): T;
export declare function pending(): string[];
export declare function ask<T = any>(prompt: string, opts?: NaksOptions): Promise<T>;

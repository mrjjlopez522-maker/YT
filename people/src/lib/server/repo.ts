// A deliberately small data-access interface. Business rules and authorization
// live in service.ts and run identically on both implementations:
//   - MemoryRepo: demo mode, local fixtures, one process.
//   - PgRepo:     production, Postgres (Supabase) with real transactions and row locks.

import type { TableName, Tables } from "./schema";

export type Cond<V> = V | V[] | { gt: V } | { gte: V } | { lt: V } | { ne: V } | { isNull: boolean };
export type Where<R> = { [K in keyof R]?: Cond<R[K]> };

export interface SelectOpts<R> {
  forUpdate?: boolean;
  orderBy?: keyof R;
  desc?: boolean;
  limit?: number;
}

export interface Tx {
  select<T extends TableName>(table: T, where?: Where<Tables[T]>, opts?: SelectOpts<Tables[T]>): Promise<Tables[T][]>;
  insert<T extends TableName>(table: T, row: Tables[T]): Promise<Tables[T]>;
  update<T extends TableName>(table: T, where: Where<Tables[T]>, patch: Partial<Tables[T]>): Promise<Tables[T][]>;
  delete<T extends TableName>(table: T, where: Where<Tables[T]>): Promise<number>;
  count<T extends TableName>(table: T, where?: Where<Tables[T]>): Promise<number>;
}

export interface Repo {
  /** Run fn atomically. Throwing rolls back every write made inside. */
  tx<R>(fn: (tx: Tx) => Promise<R>): Promise<R>;
}

/** Thrown for a unique-constraint conflict so the service can map it to a friendly error. */
export class ConflictError extends Error {
  constructor(message = "conflict") {
    super(message);
    this.name = "ConflictError";
  }
}

export function matches<R>(row: R, where: Where<R> = {}): boolean {
  for (const key in where) {
    const cond = where[key] as unknown;
    const v = row[key as keyof R] as unknown;
    if (Array.isArray(cond)) {
      if (!cond.includes(v)) return false;
    } else if (cond !== null && typeof cond === "object") {
      const c = cond as Record<string, unknown>;
      if ("gt" in c && !(v != null && (v as string) > (c.gt as string))) return false;
      if ("gte" in c && !(v != null && (v as string) >= (c.gte as string))) return false;
      if ("lt" in c && !(v != null && (v as string) < (c.lt as string))) return false;
      if ("ne" in c && v === c.ne) return false;
      if ("isNull" in c && (v == null) !== c.isNull) return false;
    } else if (v !== cond) return false;
  }
  return true;
}

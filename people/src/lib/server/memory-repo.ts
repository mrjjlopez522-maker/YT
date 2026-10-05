// In-memory repo for demo mode. Transactions are serialised with a mutex and
// rolled back from a snapshot on error, so concurrent requests behave like the
// Postgres repo (one winner, no partial writes).

import { ConflictError, matches, type Repo, type SelectOpts, type Tx, type Where } from "./repo";
import type { TableName, Tables } from "./schema";

type Data = { [T in TableName]: Tables[T][] };

// Mirrors the UNIQUE / partial unique indexes in the SQL migration.
const UNIQUE: { [T in TableName]?: { cols: (keyof Tables[T])[]; when?: (r: Tables[T]) => boolean }[] } = {
  profiles: [{ cols: ["id"] }],
  helper_topics: [{ cols: ["helperId", "topicId"] }],
  invitations: [{ cols: ["requestId"], when: (r) => r.status === "pending" }, { cols: ["requestId", "helperId"] }],
  sessions: [{ cols: ["requestId"] }],
  session_participants: [{ cols: ["sessionId", "userId"] }],
  shared_notes: [{ cols: ["sessionId"] }],
  private_notes: [{ cols: ["sessionId", "userId"] }],
  feedback: [{ cols: ["sessionId", "fromUser"] }],
  blocks: [{ cols: ["blockerId", "blockedId"] }],
};

export function emptyData(): Data {
  return {
    profiles: [], helper_topics: [], availability_windows: [], requests: [], invitations: [], sessions: [],
    session_participants: [], messages: [], checklist_items: [], shared_notes: [], private_notes: [], takeaways: [],
    feedback: [], blocks: [], reports: [], credential_reviews: [], moderation_actions: [], async_responses: [],
  };
}

const clone = <V>(v: V): V => structuredClone(v);

export class MemoryRepo implements Repo {
  data: Data;
  private lock: Promise<unknown> = Promise.resolve();

  constructor(data: Data = emptyData()) {
    this.data = data;
  }

  private checkUnique<T extends TableName>(table: T, rows: Tables[T][]) {
    for (const u of UNIQUE[table] ?? []) {
      const seen = new Set<string>();
      for (const r of rows) {
        if (u.when && !u.when(r)) continue;
        const key = u.cols.map((c) => String(r[c])).join("|");
        if (seen.has(key)) throw new ConflictError(`${table} unique(${u.cols.join(",")})`);
        seen.add(key);
      }
    }
  }

  async tx<R>(fn: (tx: Tx) => Promise<R>): Promise<R> {
    const run = async () => {
      const snapshot = clone(this.data);
      const d = this.data;
      const self = this;
      const tx: Tx = {
        async select<T extends TableName>(table: T, where?: Where<Tables[T]>, opts: SelectOpts<Tables[T]> = {}) {
          let rows = (d[table] as Tables[T][]).filter((r) => matches(r, where));
          if (opts.orderBy) {
            const k = opts.orderBy;
            rows = [...rows].sort((a, b) => (a[k] < b[k] ? -1 : a[k] > b[k] ? 1 : 0) * (opts.desc ? -1 : 1));
          }
          if (opts.limit != null) rows = rows.slice(0, opts.limit);
          return clone(rows);
        },
        async insert<T extends TableName>(table: T, row: Tables[T]) {
          const next = [...(d[table] as Tables[T][]), clone(row)];
          self.checkUnique(table, next);
          (d[table] as Tables[T][]) = next;
          return clone(row);
        },
        async update<T extends TableName>(table: T, where: Where<Tables[T]>, patch: Partial<Tables[T]>) {
          const out: Tables[T][] = [];
          const next = (d[table] as Tables[T][]).map((r) => {
            if (!matches(r, where)) return r;
            const n = { ...r, ...clone(patch) };
            out.push(n);
            return n;
          });
          self.checkUnique(table, next);
          (d[table] as Tables[T][]) = next;
          return clone(out);
        },
        async delete<T extends TableName>(table: T, where: Where<Tables[T]>) {
          const before = d[table].length;
          (d[table] as Tables[T][]) = (d[table] as Tables[T][]).filter((r) => !matches(r, where));
          return before - d[table].length;
        },
        async count<T extends TableName>(table: T, where?: Where<Tables[T]>) {
          return (d[table] as Tables[T][]).filter((r) => matches(r, where)).length;
        },
      };
      try {
        return await fn(tx);
      } catch (e) {
        this.data = snapshot;
        throw e;
      }
    };
    const p = this.lock.then(run, run);
    this.lock = p.catch(() => undefined);
    return p;
  }
}

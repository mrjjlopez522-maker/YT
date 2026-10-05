// Postgres repo for production (Supabase's Postgres or any Postgres 15+).
// Server-only: it connects with DATABASE_URL, which must never reach the browser.
// Each tx() is a real transaction; `forUpdate` takes row locks so concurrent
// acceptances serialise. Row-level security still protects every table from
// direct client access through Supabase's public API (see the migrations).

import "server-only";
import { Pool, type PoolClient } from "pg";
import { ConflictError, type Repo, type SelectOpts, type Tx, type Where } from "./repo";
import { SCHEMA, snake, type TableName, type Tables } from "./schema";
import { buildWhere, fromDb, toDb } from "./pg-sql";

export class PgRepo implements Repo {
  constructor(private pool: Pool) {}

  /**
   * DATABASE_CA_CERT (PEM text, e.g. Supabase's downloadable root certificate)
   * enables verified TLS. Leave sslmode out of DATABASE_URL when using it.
   */
  static fromUrl(url: string) {
    const ca = process.env.DATABASE_CA_CERT?.replace(/\\n/g, "\n");
    return new PgRepo(new Pool({ connectionString: url, max: 5, ...(ca ? { ssl: { ca, rejectUnauthorized: true } } : {}) }));
  }

  async tx<R>(fn: (tx: Tx) => Promise<R>): Promise<R> {
    const client = await this.pool.connect();
    try {
      await client.query("begin");
      const result = await fn(makeTx(client));
      await client.query("commit");
      return result;
    } catch (e) {
      await client.query("rollback").catch(() => undefined);
      const err = e as { code?: string; message?: string };
      if (err.code === "23505") throw new ConflictError(err.message);
      throw e;
    } finally {
      client.release();
    }
  }

  end() {
    return this.pool.end();
  }
}

export function makeTx(raw: Pick<PoolClient, "query">): Tx {
  // Surface unique violations as ConflictError inside the transaction too, so the
  // service can turn them into friendly messages (the transaction still rolls back).
  const client = {
    async query(sql: string, params: unknown[]) {
      try {
        return await raw.query(sql, params);
      } catch (e) {
        const err = e as { code?: string; message?: string };
        if (err.code === "23505") throw new ConflictError(err.message);
        throw e;
      }
    },
  };
  return {
    async select<T extends TableName>(table: T, where?: Where<Tables[T]>, opts: SelectOpts<Tables[T]> = {}) {
      const params: unknown[] = [];
      let sql = `select * from public.${table}${buildWhere(table, where, params)}`;
      if (opts.orderBy) {
        if (!(String(opts.orderBy) in SCHEMA[table])) throw new Error("bad orderBy");
        sql += ` order by ${snake(String(opts.orderBy))} ${opts.desc ? "desc" : "asc"}`;
      }
      if (opts.limit != null) sql += ` limit ${Math.max(0, Math.floor(opts.limit))}`;
      if (opts.forUpdate) sql += " for update";
      const res = await client.query(sql, params);
      return res.rows.map((r) => fromDb(table, r));
    },
    async insert<T extends TableName>(table: T, row: Tables[T]) {
      const db = toDb(table, row);
      const cols = Object.keys(db);
      const params = cols.map((c) => db[c]);
      const sql = `insert into public.${table} (${cols.join(",")}) values (${cols.map((_, i) => `$${i + 1}`).join(",")}) returning *`;
      const res = await client.query(sql, params);
      return fromDb(table, res.rows[0]);
    },
    async update<T extends TableName>(table: T, where: Where<Tables[T]>, patch: Partial<Tables[T]>) {
      const db = toDb(table, patch);
      const cols = Object.keys(db);
      if (cols.length === 0) return this.select(table, where);
      const params: unknown[] = cols.map((c) => db[c]);
      const set = cols.map((c, i) => `${c} = $${i + 1}`).join(", ");
      const sql = `update public.${table} set ${set}${buildWhere(table, where, params)} returning *`;
      const res = await client.query(sql, params);
      return res.rows.map((r) => fromDb(table, r));
    },
    async delete<T extends TableName>(table: T, where: Where<Tables[T]>) {
      const params: unknown[] = [];
      const res = await client.query(`delete from public.${table}${buildWhere(table, where, params)}`, params);
      return res.rowCount ?? 0;
    },
    async count<T extends TableName>(table: T, where?: Where<Tables[T]>) {
      const params: unknown[] = [];
      const res = await client.query(`select count(*)::int as n from public.${table}${buildWhere(table, where, params)}`, params);
      return res.rows[0].n as number;
    },
  };
}

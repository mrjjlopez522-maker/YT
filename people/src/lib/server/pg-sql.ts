import type { Where } from "./repo";
import { SCHEMA, snake, type TableName, type Tables } from "./schema";

function colKind(table: TableName, key: string) {
  const kind = (SCHEMA[table] as Record<string, string>)[key];
  if (!kind) throw new Error(`Unknown column ${table}.${key}`);
  return kind;
}

export function buildWhere<T extends TableName>(table: T, where: Where<Tables[T]> | undefined, params: unknown[]) {
  const parts: string[] = [];
  for (const key in where ?? {}) {
    const cond = (where as Record<string, unknown>)[key];
    if (cond === undefined) continue;
    const kind = colKind(table, key);
    const col = snake(key);
    const p = (v: unknown) => {
      params.push(kind === "ts" && v != null ? new Date(v as string) : v);
      return `$${params.length}`;
    };
    if (Array.isArray(cond)) {
      if (cond.length === 0) parts.push("false");
      else {
        params.push(kind === "ts" ? cond.map((v) => new Date(v as string)) : cond);
        parts.push(`${col} = any($${params.length})`);
      }
    } else if (cond !== null && typeof cond === "object") {
      const c = cond as Record<string, unknown>;
      if ("gt" in c) parts.push(`${col} > ${p(c.gt)}`);
      if ("gte" in c) parts.push(`${col} >= ${p(c.gte)}`);
      if ("lt" in c) parts.push(`${col} < ${p(c.lt)}`);
      if ("ne" in c) parts.push(`${col} is distinct from ${p(c.ne)}`);
      if ("isNull" in c) parts.push(`${col} is ${c.isNull ? "" : "not "}null`);
    } else if (cond === null) {
      parts.push(`${col} is null`);
    } else {
      parts.push(`${col} = ${p(cond)}`);
    }
  }
  return parts.length ? ` where ${parts.join(" and ")}` : "";
}

export function toDb<T extends TableName>(table: T, row: Partial<Tables[T]>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key in row) {
    const v = (row as Record<string, unknown>)[key];
    if (v === undefined) continue;
    const kind = colKind(table, key);
    out[snake(key)] = kind === "ts" && v != null ? new Date(v as string) : v;
  }
  return out;
}

export function fromDb<T extends TableName>(table: T, r: Record<string, unknown>): Tables[T] {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(SCHEMA[table])) {
    const v = r[snake(key)];
    const kind = colKind(table, key);
    out[key] = kind === "ts" ? (v == null ? null : (v as Date).toISOString()) : v;
  }
  return out as unknown as Tables[T];
}

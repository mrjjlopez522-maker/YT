// Runs the full service suite against real Postgres with the real migrations,
// then checks constraints, triggers and row-level security directly.
// Requires DATABASE_URL_TEST (e.g. postgres://postgres:postgres@localhost:5432/people_test).
// WARNING: it drops and recreates the public schema of that database.

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PgRepo } from "../../src/lib/server/pg-repo";
import { SCHEMA, snake } from "../../src/lib/server/schema";
import { DEMO_IDS, makeHarness } from "../shared/harness";
import { serviceSuite } from "../shared/service-suite";

const url = process.env.DATABASE_URL_TEST;
const d = url ? describe : describe.skip;
const pool = url ? new Pool({ connectionString: url, max: 6 }) : (null as unknown as Pool);
const repo = url ? new PgRepo(pool) : (null as unknown as PgRepo);
const root = path.resolve(__dirname, "../..");

async function migrate() {
  await pool.query("drop schema if exists public cascade; create schema public; grant usage on schema public to public;");
  await pool.query(readFileSync(path.join(__dirname, "supabase-stub.sql"), "utf8"));
  const dir = path.join(root, "supabase/migrations");
  for (const f of readdirSync(dir).sort()) await pool.query(readFileSync(path.join(dir, f), "utf8"));
}

async function reset() {
  const tables = Object.keys(SCHEMA).map((t) => `public.${t}`).join(", ");
  await pool.query(`truncate ${tables}, auth.users cascade`);
  await pool.query(`insert into auth.users (id) select unnest($1::uuid[])`, [Object.values(DEMO_IDS)]);
  return repo;
}

if (url) {
  beforeAll(migrate, 60_000);
  afterAll(() => pool.end());
}

d("postgres", () => {
  serviceSuite("postgres", reset);

  it("schema map matches the migration columns", async () => {
    for (const [table, cols] of Object.entries(SCHEMA)) {
      const res = await pool.query("select column_name from information_schema.columns where table_schema='public' and table_name=$1", [table]);
      const actual = res.rows.map((r) => r.column_name).sort();
      expect(actual, table).toEqual(Object.keys(cols).map(snake).sort());
    }
  });

  it("enforces state transitions in the database", async () => {
    const h = await makeHarness(await reset());
    const req = await h.svc.createRequest(h.as(DEMO_IDS.maya), {
      question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice", language: "en", formats: ["text"], timing: "now",
    });
    await expect(pool.query("update public.requests set status='closed' where id=$1", [req.id])).rejects.toThrow(/invalid requests transition/);
    const ma = await pool.query("select count(*)::int n from public.moderation_actions");
    expect(ma.rows[0].n).toBeGreaterThan(0);
    await expect(pool.query("delete from public.moderation_actions")).rejects.toThrow(/append-only/);
    await expect(pool.query("update public.moderation_actions set reason='x'")).rejects.toThrow(/append-only/);
  });

  async function asUser(uid: string | null, sql: string, params: unknown[] = []) {
    const c = await pool.connect();
    try {
      await c.query("begin");
      await c.query(`set local role ${uid ? "authenticated" : "anon"}`);
      if (uid) await c.query("select set_config('request.jwt.claims', $1, true)", [JSON.stringify({ sub: uid, role: "authenticated" })]);
      const r = await c.query(sql, params);
      await c.query("rollback");
      return r.rows;
    } catch (e) {
      await c.query("rollback");
      throw e;
    } finally {
      c.release();
    }
  }

  it("row-level security keeps sessions, messages and notes private", async () => {
    const h = await makeHarness(await reset());
    const { maya, priya, chris, sam } = DEMO_IDS;
    const sid = "00000000-0000-4000-d000-000000000001"; // Maya ↔ Priya fixture session
    await h.svc.updatePrivateNote(h.as(maya), sid, "secret");

    expect(await asUser(maya, "select id from public.messages where session_id=$1", [sid])).not.toHaveLength(0);
    expect(await asUser(priya, "select id from public.messages where session_id=$1", [sid])).not.toHaveLength(0);
    expect(await asUser(chris, "select id from public.messages where session_id=$1", [sid])).toHaveLength(0);
    expect(await asUser(chris, "select id from public.sessions")).toHaveLength(0);
    expect(await asUser(chris, "select id from public.requests")).toHaveLength(0);
    expect(await asUser(priya, "select body from public.private_notes")).toHaveLength(0);
    expect(await asUser(maya, "select body from public.private_notes")).toHaveLength(1);
    expect(await asUser(sam, "select id from public.messages")).toHaveLength(0); // moderators read evidence via the audited server path only
    expect(await asUser(maya, "select id from public.reports")).toHaveLength(0);
    expect(await asUser(sam, "select id from public.reports")).not.toHaveLength(0);
    expect(await asUser(maya, "select id from public.moderation_actions")).toHaveLength(0);
    expect(await asUser(null, "select id from public.topics")).not.toHaveLength(0);
    await expect(asUser(null, "select id from public.profiles")).rejects.toThrow(/permission denied/);
  });

  it("clients cannot write directly, even into their own session", async () => {
    await reset();
    const { maya } = DEMO_IDS;
    const sid = "00000000-0000-4000-d000-000000000001";
    await expect(asUser(maya, "insert into public.messages (session_id, sender_id, body) values ($1, $2, 'hi')", [sid, maya])).rejects.toThrow(/permission denied/);
    await expect(asUser(maya, "update public.profiles set role='moderator' where id=$1", [maya])).rejects.toThrow(/permission denied/);
    await expect(asUser(maya, "insert into public.credential_reviews (user_id, topic_id, title, status, reviewed_by) values ($1,'cooking','x','verified',$1)", [maya])).rejects.toThrow(/permission denied/);
  });

  it("the database rejects a second pending invitation and a second session per request", async () => {
    const h = await makeHarness(await reset());
    const req = await h.svc.createRequest(h.as(DEMO_IDS.maya), {
      question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice", language: "en", formats: ["text"], timing: "now",
    });
    await h.svc.inviteHelper(h.as(DEMO_IDS.maya), req.id, DEMO_IDS.chris);
    await expect(pool.query(
      "insert into public.invitations (request_id, requester_id, helper_id, expires_at) values ($1, $2, $3, now() + interval '1 hour')",
      [req.id, DEMO_IDS.maya, DEMO_IDS.priya],
    )).rejects.toThrow(/invitations_one_pending_per_request/);
  });
});

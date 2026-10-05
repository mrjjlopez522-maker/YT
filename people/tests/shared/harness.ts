import { buildDemoData, DEMO_IDS } from "../../src/lib/demo/fixtures";
import type { Repo } from "../../src/lib/server/repo";
import type { TableName } from "../../src/lib/server/schema";
import { Service, type TokenMinter } from "../../src/lib/server/service";
import type { Viewer } from "../../src/lib/domain/types";

// Slightly in the future so database-side now() checks (deadlines) agree with the fake clock.
export const T0 = new Date(Math.ceil(Date.now() / 3_600_000) * 3_600_000 + 3_600_000);

export interface Harness {
  svc: Service;
  repo: Repo;
  clock: { t: number; advance(ms: number): void };
  as(id: string): Viewer;
  minted: Parameters<TokenMinter>[0][];
}

// Insert order respects foreign keys in the SQL schema.
const ORDER: TableName[] = [
  "profiles", "helper_topics", "availability_windows", "credential_reviews", "requests", "invitations", "sessions",
  "session_participants", "messages", "checklist_items", "shared_notes", "private_notes", "takeaways", "feedback",
  "blocks", "reports", "moderation_actions", "async_responses",
];

export async function seed(repo: Repo, now = T0) {
  const data = buildDemoData(now);
  await repo.tx(async (tx) => {
    for (const t of ORDER) for (const row of data[t] as never[]) await tx.insert(t, row);
  });
}

export async function makeHarness(repo: Repo, opts: { withLiveKit?: boolean } = {}): Promise<Harness> {
  await seed(repo);
  const clock = { t: T0.getTime(), advance(ms: number) { this.t += ms; } };
  const minted: Parameters<TokenMinter>[0][] = [];
  const svc = new Service({
    repo,
    now: () => new Date(clock.t),
    mintToken: opts.withLiveKit === false ? null : async (a) => { minted.push(a); return { token: `tok-${a.identity}`, url: "wss://example.livekit" }; },
  });
  return {
    svc, repo, clock, minted,
    as: (id) => ({ id, role: id === DEMO_IDS.sam ? "moderator" : "member", status: "active" }),
  };
}

export { DEMO_IDS };

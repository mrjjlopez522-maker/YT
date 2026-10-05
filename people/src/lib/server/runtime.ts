import "server-only";
import { serverConfig } from "../config";
import { buildDemoData } from "../demo/fixtures";
import { publish } from "./events";
import { livekitMinter } from "./livekit";
import { MemoryRepo } from "./memory-repo";
import { PgRepo } from "./pg-repo";
import { Service } from "./service";

const g = globalThis as unknown as { __peopleService?: Service; __peopleDemoRepo?: MemoryRepo };

/** One service per server process. Demo data lives only in this process's memory. */
export function getService(): Service {
  if (g.__peopleService) return g.__peopleService;
  const cfg = serverConfig();
  const repo = cfg.mode === "live" ? PgRepo.fromUrl(cfg.supabase.databaseUrl) : (g.__peopleDemoRepo = new MemoryRepo(buildDemoData()));
  g.__peopleService = new Service({
    repo,
    notify: publish,
    mintToken: cfg.livekit.configured ? livekitMinter(cfg.livekit) : null,
  });
  return g.__peopleService;
}

/** Demo only: put the sample data back to its starting state. */
export function resetDemo() {
  if (serverConfig().mode !== "demo" || !g.__peopleDemoRepo) return;
  g.__peopleDemoRepo.data = buildDemoData();
}

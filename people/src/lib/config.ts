// What is configured on this server. Read only on the server; the browser
// receives a small, secret-free summary via publicConfig().

export type Mode = "demo" | "live";

export function serverConfig() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  const databaseUrl = process.env.DATABASE_URL ?? "";
  const forcedDemo = process.env.PEOPLE_MODE === "demo";
  const supabase = !!(supabaseUrl && supabaseAnonKey && databaseUrl);
  const livekit = !!(process.env.LIVEKIT_URL && process.env.LIVEKIT_API_KEY && process.env.LIVEKIT_API_SECRET);
  const ai = !!process.env.ANTHROPIC_API_KEY && process.env.PEOPLE_AI !== "off";
  const mode: Mode = supabase && !forcedDemo ? "live" : "demo";
  return {
    mode,
    supabase: { configured: supabase, url: supabaseUrl, anonKey: supabaseAnonKey, databaseUrl },
    livekit: { configured: livekit, url: process.env.LIVEKIT_URL ?? "", apiKey: process.env.LIVEKIT_API_KEY ?? "", apiSecret: process.env.LIVEKIT_API_SECRET ?? "" },
    ai: { configured: ai },
  };
}

export interface PublicConfig {
  mode: Mode;
  livekit: boolean;
  ai: boolean;
  supabaseUrl: string | null;
  supabaseAnonKey: string | null;
}

/** Safe to send to the browser: no secrets. The anon key is public by design and protected by RLS. */
export function publicConfig(): PublicConfig {
  const c = serverConfig();
  return {
    mode: c.mode,
    livekit: c.livekit.configured,
    ai: c.ai.configured,
    supabaseUrl: c.mode === "live" ? c.supabase.url : null,
    supabaseAnonKey: c.mode === "live" ? c.supabase.anonKey : null,
  };
}

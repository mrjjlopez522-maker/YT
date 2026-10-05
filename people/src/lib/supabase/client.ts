"use client";
import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

/** Browser client with the public anon key. Every table it can read is RLS-protected. */
export function supabaseBrowser(url: string, anonKey: string) {
  return (client ??= createBrowserClient(url, anonKey));
}

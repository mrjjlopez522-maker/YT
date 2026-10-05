import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { serverConfig } from "../config";
import { supabaseServer } from "../supabase/server";
import { getService } from "./runtime";
import type { Profile, Viewer } from "../domain/types";

export const DEMO_COOKIE = "people_demo_as";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The authenticated account id, or null. Never derived from anything the client can forge in live mode. */
export async function currentUserId(): Promise<string | null> {
  if (serverConfig().mode === "demo") {
    // Demo mode has no real accounts: a cookie picks which sample person you are.
    const id = (await cookies()).get(DEMO_COOKIE)?.value ?? "";
    return UUID.test(id) ? id : null;
  }
  const supabase = await supabaseServer();
  const { data } = await supabase.auth.getUser(); // verified with the Auth server
  return data.user?.id ?? null;
}

export async function currentViewer(): Promise<{ viewer: Viewer; profile: Profile } | null> {
  const id = await currentUserId();
  if (!id) return null;
  return getService().viewerFor(id);
}

/** For pages: signed in + onboarded + not suspended, or redirect. */
export async function requireViewer() {
  const id = await currentUserId();
  if (!id) redirect("/login");
  const v = await getService().viewerFor(id);
  if (!v || !v.profile.onboarded) redirect("/onboarding");
  if (v.profile.status !== "active") redirect("/suspended");
  return v;
}

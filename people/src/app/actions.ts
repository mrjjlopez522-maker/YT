"use server";

// Server actions: the only write path from the browser. Each one resolves the
// viewer on the server and delegates to the service, which re-checks every rule.

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { getCategorizer } from "@/lib/ai/categorize";
import { serverConfig } from "@/lib/config";
import { DEMO_PERSONAS } from "@/lib/demo/fixtures";
import { currentUserId, DEMO_COOKIE } from "@/lib/server/auth";
import { getService, resetDemo } from "@/lib/server/runtime";
import { AppError, isAppError } from "@/lib/server/service";
import { supabaseServer } from "@/lib/supabase/server";
import type { Viewer } from "@/lib/domain/types";

export type Result<T = null> = { ok: true; data: T } | { ok: false; error: string; code?: string };

async function run<T>(fn: (v: Viewer) => Promise<T>): Promise<Result<T>> {
  const id = await currentUserId();
  if (!id) return { ok: false, error: "Please sign in.", code: "unauthenticated" };
  // Role and status come from the database inside the service; these are only hints.
  const found = await getService().viewerFor(id);
  const viewer: Viewer = found?.viewer ?? { id, role: "member", status: "active" };
  try {
    return { ok: true, data: await fn(viewer) };
  } catch (e) {
    if (isAppError(e)) return { ok: false, error: e.message, code: e.code };
    if (e instanceof z.ZodError) return { ok: false, error: "Some fields look off. Please check and try again.", code: "invalid" };
    console.error(e);
    return { ok: false, error: "Something went wrong on our side. Please try again." };
  }
}

const uuid = z.string().uuid();
const format = z.enum(["text", "voice", "video"]);

// ───────── auth ─────────

export async function demoSignIn(personaId: string) {
  if (serverConfig().mode !== "demo") throw new Error("Demo sign-in is disabled when Supabase is configured.");
  const allowed = DEMO_PERSONAS.some((p) => p.id === personaId);
  const id = allowed ? personaId : crypto.randomUUID(); // anything else = a brand-new demo person
  (await cookies()).set(DEMO_COOKIE, id, { httpOnly: true, sameSite: "lax", path: "/", secure: process.env.NODE_ENV === "production" });
  redirect(allowed ? "/" : "/onboarding");
}

export async function signOut() {
  if (serverConfig().mode === "demo") (await cookies()).delete(DEMO_COOKIE);
  else await (await supabaseServer()).auth.signOut();
  redirect("/login");
}

export async function sendMagicLink(email: string, origin: string): Promise<Result> {
  if (serverConfig().mode !== "live") return { ok: false, error: "Email sign-in needs Supabase to be configured." };
  const parsed = z.string().email().safeParse(email.trim());
  if (!parsed.success) return { ok: false, error: "Enter a valid email address." };
  const supabase = await supabaseServer();
  const { error } = await supabase.auth.signInWithOtp({
    email: parsed.data,
    options: { emailRedirectTo: `${origin}/auth/callback`, shouldCreateUser: process.env.PEOPLE_INVITE_ONLY !== "true" },
  });
  if (error) return { ok: false, error: error.message };
  return { ok: true, data: null };
}

export async function resetDemoData(): Promise<Result> {
  if (serverConfig().mode !== "demo") return { ok: false, error: "Only available in demo mode." };
  resetDemo();
  revalidatePath("/", "layout");
  return { ok: true, data: null };
}

// ───────── profile ─────────

const ProfileInput = z.object({
  displayName: z.string().max(40),
  intro: z.string().max(400),
  canHelpWith: z.string().max(400),
  curiousAbout: z.string().max(400),
  languages: z.array(z.string().max(10)).max(8),
  formats: z.array(format),
  timezone: z.string().max(60),
  locationBroad: z.string().max(60),
  interests: z.array(z.string().max(60)).max(12),
  cannotAdvise: z.string().max(400),
  sessionLengthMinutes: z.number().int(),
  adultConfirmed: z.boolean(),
});

export async function saveProfile(input: z.infer<typeof ProfileInput>): Promise<Result> {
  const id = await currentUserId();
  if (!id) return { ok: false, error: "Please sign in." };
  try {
    await getService().saveProfile(id, ProfileInput.parse(input));
    revalidatePath("/", "layout");
    return { ok: true, data: null };
  } catch (e) {
    if (isAppError(e)) return { ok: false, error: e.message };
    if (e instanceof z.ZodError) return { ok: false, error: "Some fields look off." };
    throw e;
  }
}

const HelperTopicsInput = z.array(z.object({
  topicId: z.string().max(60), kind: z.enum(["lived", "professional"]), detail: z.string().max(300), welcomesBeginners: z.boolean(),
})).max(20);

export async function saveHelperTopics(topics: z.infer<typeof HelperTopicsInput>) {
  return run(async (v) => {
    await getService().setHelperTopics(v, HelperTopicsInput.parse(topics));
    revalidatePath("/profile");
    return null;
  });
}

const WindowsInput = z.array(z.object({
  weekday: z.number().int().min(0).max(6), startMinute: z.number().int(), endMinute: z.number().int(),
})).max(28);

export async function saveAvailability(windows: z.infer<typeof WindowsInput>) {
  return run(async (v) => {
    await getService().setAvailabilityWindows(v, WindowsInput.parse(windows));
    return null;
  });
}

export async function setAvailableNow(minutes: number) {
  return run(async (v) => {
    const until = await getService().setAvailableNow(v, z.number().int().min(0).max(240).parse(minutes));
    revalidatePath("/", "layout");
    return until;
  });
}

export async function submitCredential(input: { topicId: string; title: string; issuer: string; evidenceNote: string }) {
  return run(async (v) => {
    const parsed = z.object({ topicId: z.string().max(60), title: z.string().max(120), issuer: z.string().max(120), evidenceNote: z.string().max(600) }).parse(input);
    await getService().submitCredential(v, parsed);
    revalidatePath("/profile");
    return null;
  });
}

// ───────── requests ─────────

const analyzeHits = new Map<string, number[]>();

export async function analyzeQuestion(question: string) {
  return run(async (v) => {
    const q = z.string().min(1).max(600).parse(question);
    // Per-user throttle so the optional AI provider can't be used as a free API.
    const now = Date.now();
    const hits = (analyzeHits.get(v.id) ?? []).filter((t) => now - t < 60_000);
    if (hits.length >= 20) throw new AppError("rate_limited", "Slow down a little — try again in a minute.");
    analyzeHits.set(v.id, [...hits, now]);
    return getCategorizer().analyze(q);
  });
}

const RequestInput = z.object({
  question: z.string().max(600),
  intent: z.enum(["ask", "learn", "move", "explore"]),
  topicId: z.string().max(60),
  tags: z.array(z.string().max(40)).max(8).optional(),
  language: z.string().max(10),
  formats: z.array(format).min(1),
  timing: z.enum(["now", "later"]),
  preferredTime: z.string().max(40).nullable().optional(),
  experienceLevel: z.enum(["", "new", "some", "experienced"]).optional(),
  context: z.string().max(800).optional(),
  clarificationQuestion: z.string().max(200).optional(),
  clarificationAnswer: z.string().max(400).optional(),
  autoMatch: z.boolean().optional(),
});

export async function createRequest(input: z.infer<typeof RequestInput>) {
  return run(async (v) => {
    const req = await getService().createRequest(v, RequestInput.parse(input));
    revalidatePath("/requests");
    return { id: req.id };
  });
}

export async function inviteHelper(requestId: string, helperId: string) {
  return run(async (v) => {
    await getService().inviteHelper(v, uuid.parse(requestId), uuid.parse(helperId));
    revalidatePath(`/requests/${requestId}`);
    return null;
  });
}

export async function startAutoMatch(requestId: string) {
  return run(async (v) => {
    await getService().startAutoMatch(v, uuid.parse(requestId));
    revalidatePath(`/requests/${requestId}`);
    return null;
  });
}

export async function broadenRequest(requestId: string, key: "formats" | "topic" | "timing", preferredTime?: string) {
  return run(async (v) => {
    await getService().broaden(v, uuid.parse(requestId), z.enum(["formats", "topic", "timing"]).parse(key), preferredTime);
    revalidatePath(`/requests/${requestId}`);
    return null;
  });
}

export async function leaveForLater(requestId: string) {
  return run(async (v) => {
    await getService().leaveForLater(v, uuid.parse(requestId));
    revalidatePath(`/requests/${requestId}`);
    return null;
  });
}

export async function cancelRequest(requestId: string) {
  return run(async (v) => {
    await getService().cancelRequest(v, uuid.parse(requestId));
    revalidatePath("/requests");
    return null;
  });
}

export async function cancelInvitation(invitationId: string) {
  return run(async (v) => {
    await getService().cancelInvitation(v, uuid.parse(invitationId));
    revalidatePath("/requests");
    return null;
  });
}

export async function respondInvitation(invitationId: string, accept: boolean) {
  return run(async (v) => {
    const res = await getService().respondInvitation(v, uuid.parse(invitationId), accept);
    revalidatePath("/helping");
    return res;
  });
}

export async function respondAsync(requestId: string, body: string) {
  return run(async (v) => {
    await getService().respondAsync(v, uuid.parse(requestId), z.string().max(3000).parse(body));
    revalidatePath("/helping");
    return null;
  });
}

export async function surpriseMe() {
  return run((v) => getService().surprise(v));
}

// ───────── sessions ─────────

export async function sendMessage(sessionId: string, body: string) {
  return run(async (v) => { await getService().sendMessage(v, uuid.parse(sessionId), z.string().max(2000).parse(body)); return null; });
}

export async function addChecklistItem(sessionId: string, text: string, kind: "step" | "try" | "task") {
  return run(async (v) => { await getService().addChecklistItem(v, uuid.parse(sessionId), z.string().max(200).parse(text), kind); return null; });
}

export async function toggleChecklistItem(sessionId: string, itemId: string, done: boolean) {
  return run(async (v) => { await getService().toggleChecklistItem(v, uuid.parse(sessionId), uuid.parse(itemId), !!done); return null; });
}

export async function removeChecklistItem(sessionId: string, itemId: string) {
  return run(async (v) => { await getService().removeChecklistItem(v, uuid.parse(sessionId), uuid.parse(itemId)); return null; });
}

export async function saveSharedNote(sessionId: string, body: string) {
  return run(async (v) => { await getService().updateSharedNote(v, uuid.parse(sessionId), z.string().max(8000).parse(body)); return null; });
}

export async function savePrivateNote(sessionId: string, body: string) {
  return run(async (v) => { await getService().updatePrivateNote(v, uuid.parse(sessionId), z.string().max(8000).parse(body)); return null; });
}

export async function setGoal(sessionId: string, goal: string) {
  return run(async (v) => { await getService().setGoal(v, uuid.parse(sessionId), z.string().max(300).parse(goal)); return null; });
}

export async function setSessionFlag(sessionId: string, flag: "videoOptIn" | "keepGoing", value: boolean) {
  return run(async (v) => { await getService().setParticipantFlag(v, uuid.parse(sessionId), z.enum(["videoOptIn", "keepGoing"]).parse(flag), !!value); return null; });
}

export async function setTimer(sessionId: string, minutes: number, label: string) {
  return run(async (v) => { await getService().setTimer(v, uuid.parse(sessionId), z.number().parse(minutes), z.string().max(60).parse(label)); return null; });
}

export async function startSession(sessionId: string) {
  return run(async (v) => { await getService().startSession(v, uuid.parse(sessionId)); return null; });
}

export async function endSession(sessionId: string) {
  return run(async (v) => { await getService().endSession(v, uuid.parse(sessionId)); revalidatePath("/sessions"); return null; });
}

export async function wrapUp(sessionId: string, input: { addressed: "" | "yes" | "partly" | "no"; reconnect: boolean; helpful?: number; respectful?: boolean; comment?: string }) {
  return run(async (v) => {
    const parsed = z.object({
      addressed: z.enum(["", "yes", "partly", "no"]), reconnect: z.boolean(), helpful: z.number().int().min(1).max(5).optional(),
      respectful: z.boolean().optional(), comment: z.string().max(1000).optional(),
    }).parse(input);
    await getService().wrapUp(v, uuid.parse(sessionId), parsed);
    return null;
  });
}

export async function requestFollowUp(sessionId: string, input: { question: string; timing: "now" | "later"; preferredTime?: string }) {
  return run(async (v) => {
    const res = await getService().requestFollowUp(v, uuid.parse(sessionId), z.object({
      question: z.string().max(600), timing: z.enum(["now", "later"]), preferredTime: z.string().max(40).optional(),
    }).parse(input));
    return { requestId: res.request.id };
  });
}

// ───────── learning ─────────

export async function addTakeaway(input: { sessionId?: string | null; title: string; body: string; nextSteps: string }) {
  return run(async (v) => {
    await getService().addTakeaway(v, z.object({
      sessionId: uuid.nullable().optional(), title: z.string().max(120), body: z.string().max(8000), nextSteps: z.string().max(2000),
    }).parse(input));
    revalidatePath("/learning");
    return null;
  });
}

export async function deleteTakeaway(id: string) {
  return run(async (v) => { await getService().deleteTakeaway(v, uuid.parse(id)); revalidatePath("/learning"); return null; });
}

// ───────── safety ─────────

export async function blockPerson(userId: string) {
  return run(async (v) => { await getService().block(v, uuid.parse(userId)); revalidatePath("/", "layout"); return null; });
}

export async function unblockPerson(userId: string) {
  return run(async (v) => { await getService().unblock(v, uuid.parse(userId)); revalidatePath("/profile"); return null; });
}

const reasons = z.enum(["harassment", "inappropriate_media", "spam", "unsafe_advice", "impersonation", "other"]);

export async function reportPerson(input: { userId: string; sessionId?: string | null; reason: z.infer<typeof reasons>; details: string }) {
  return run(async (v) => {
    await getService().report(v, z.object({ userId: uuid, sessionId: uuid.nullable().optional(), reason: reasons, details: z.string().max(2000) }).parse(input));
    return null;
  });
}

// ───────── moderation ─────────

export async function modResolveReport(reportId: string, outcome: "actioned" | "dismissed", reason: string) {
  return run(async (v) => { await getService().resolveReport(v, uuid.parse(reportId), z.enum(["actioned", "dismissed"]).parse(outcome), z.string().max(1000).parse(reason)); revalidatePath("/moderation"); return null; });
}

export async function modSetSuspended(userId: string, suspended: boolean, reason: string) {
  return run(async (v) => { await getService().setSuspended(v, uuid.parse(userId), !!suspended, z.string().max(1000).parse(reason)); revalidatePath("/moderation"); return null; });
}

export async function modReviewCredential(id: string, status: "verified" | "rejected" | "revoked", note: string) {
  return run(async (v) => { await getService().reviewCredential(v, uuid.parse(id), z.enum(["verified", "rejected", "revoked"]).parse(status), z.string().max(600).parse(note)); revalidatePath("/moderation"); return null; });
}

export async function modEvidence(reportId: string) {
  return run((v) => getService().reportEvidence(v, uuid.parse(reportId)));
}

export async function modSearch(q: string) {
  return run(async (v) => (await getService().searchPeople(v, z.string().max(60).parse(q))).map((p) => ({ id: p.id, displayName: p.displayName, status: p.status, role: p.role })));
}

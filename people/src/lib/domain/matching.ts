// Matching = hard eligibility filter, then a small, explainable score.
//
// A score only orders people who already passed the filter. It is NOT a
// measure of expertise or of whether someone's answer is correct, and new
// helpers with no feedback are scored neutrally rather than penalised.

import { languageFit, languageName } from "./languages";
import { getTopic, isHighStakes, topicAffinity, topicLineage } from "./topics";
import type { AvailabilityWindow, Format, HelpRequest, HelperTopic, Profile } from "./types";

export interface Candidate {
  profile: Profile;
  topics: HelperTopic[];
  verifiedTopicIds: string[]; // topics with a credential reviewed by the platform
  windows: AvailabilityWindow[];
  busy: boolean; // in an active session, or booked at the requested time
  feedback: { count: number; avgHelpful: number }; // relevant (same category) feedback only
}

export interface MatchContext {
  request: HelpRequest;
  now: Date;
  /** user ids blocked by, or blocking, the requester */
  blockedIds: Set<string>;
  /** helpers already invited for this request (declined/expired/etc.) */
  alreadyInvited: Set<string>;
}

export type Exclusion =
  | "self"
  | "inactive"
  | "blocked"
  | "language"
  | "format"
  | "topic"
  | "unavailable"
  | "busy"
  | "already_invited"
  | "high_stakes";

export interface Match {
  helperId: string;
  score: number;
  reasons: string[];
  topic: HelperTopic;
  verified: boolean;
  formats: Format[]; // formats both sides accept
}

const FORMAT_LABEL: Record<Format, string> = { text: "text", voice: "voice", video: "video" };

export function acceptedFormats(req: HelpRequest): Format[] {
  if (req.broadened.includes("formats")) return ["text", "voice", "video"];
  return req.formats;
}

function minTopicAffinity(req: HelpRequest): number {
  const depth = topicLineage(req.topicId).length;
  // A request on a leaf wants at least the same subtopic; a broadened request accepts the category.
  if (req.broadened.includes("topic")) return 1;
  return Math.min(depth, 2);
}

function bestTopic(req: HelpRequest, topics: HelperTopic[]) {
  let best: { t: HelperTopic; aff: number } | null = null;
  for (const t of topics) {
    const aff = topicAffinity(req.topicId, t.topicId);
    // A helper's broader topic covers a narrower request only one level down.
    if (!best || aff > best.aff) best = { t, aff };
  }
  return best;
}

/** Is the helper's weekly window covering the requested time (in the helper's timezone)? */
export function windowCovers(windows: AvailabilityWindow[], timezone: string, iso: string): boolean {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone || "UTC",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hourCycle: "h23",
  }).formatToParts(d);
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(parts.find((p) => p.type === "weekday")!.value);
  const minute = Number(parts.find((p) => p.type === "hour")!.value) * 60 + Number(parts.find((p) => p.type === "minute")!.value);
  return windows.some((w) => w.weekday === wd && minute >= w.startMinute && minute < w.endMinute);
}

export function isAvailableNow(p: Profile, now: Date) {
  return !!p.availableUntil && new Date(p.availableUntil).getTime() > now.getTime();
}

export function exclusionFor(c: Candidate, ctx: MatchContext): Exclusion | null {
  const { request: req, now } = ctx;
  const p = c.profile;
  if (isHighStakes(req.topicId)) return "high_stakes";
  if (p.id === req.requesterId) return "self";
  if (p.status !== "active" || !p.onboarded || !p.adultConfirmed) return "inactive";
  if (ctx.blockedIds.has(p.id)) return "blocked";
  if (ctx.alreadyInvited.has(p.id)) return "already_invited";
  if (languageFit(req.language, p.languages) === 0) return "language";
  if (!acceptedFormats(req).some((f) => p.formats.includes(f))) return "format";
  const best = bestTopic(req, c.topics);
  if (!best || best.aff < minTopicAffinity(req)) return "topic";
  if (req.timing === "now") {
    if (!isAvailableNow(p, now)) return "unavailable";
  } else if (req.preferredTime) {
    if (!windowCovers(c.windows, p.timezone, req.preferredTime)) return "unavailable";
  } else if (c.windows.length === 0) return "unavailable";
  if (c.busy) return "busy";
  return null;
}

export function scoreCandidate(c: Candidate, ctx: MatchContext): Match {
  const req = ctx.request;
  const p = c.profile;
  const reasons: string[] = [];
  let score = 0;

  const best = bestTopic(req, c.topics)!;
  const topicName = getTopic(best.t.topicId)?.name ?? best.t.topicId;
  score += best.aff >= 3 ? 40 : best.aff === 2 ? 30 : 15;
  reasons.push(best.t.kind === "professional" ? `Professional experience (self-described): ${topicName}` : `Lived experience: ${topicName}`);

  const verified = c.verifiedTopicIds.some((v) => topicAffinity(v, best.t.topicId) >= Math.min(2, topicLineage(v).length));
  if (verified) {
    score += 5;
    reasons.push("Has a credential reviewed by People for this topic");
  }

  const lf = languageFit(req.language, p.languages);
  score += lf === 2 ? 15 : 10;
  // Name the most specific variant they speak ("Jordanian Arabic" rather than "Arabic").
  const base = req.language.split("-")[0];
  const spoken = p.languages.find((l) => l === req.language && l.includes("-"))
    ?? p.languages.find((l) => l.startsWith(base + "-"))
    ?? p.languages.find((l) => l.split("-")[0] === base)!;
  reasons.push(`Speaks ${languageName(spoken)}`);

  if (best.t.welcomesBeginners) {
    if (req.experienceLevel === "new" || req.experienceLevel === "") score += 8;
    reasons.push("Welcomes beginners");
  }

  const formats = acceptedFormats(req).filter((f) => p.formats.includes(f));
  score += formats.includes(req.formats[0]) ? 10 : 5;

  if (req.timing === "now") {
    score += 10;
    reasons.push(`Available now for ${formats.map((f) => FORMAT_LABEL[f]).join(" or ")}`);
  } else {
    score += 10;
    reasons.push(`Usually free at that time for ${formats.map((f) => FORMAT_LABEL[f]).join(" or ")}`);
  }

  if (c.feedback.count >= 3) {
    // Small, bounded nudge; never enough to outweigh topic or language fit.
    score += Math.max(-6, Math.min(6, Math.round((c.feedback.avgHelpful - 3) * 3)));
    reasons.push(`Feedback from ${c.feedback.count} related sessions`);
  } else {
    reasons.push("New here — not much feedback yet");
  }

  return { helperId: p.id, score, reasons, topic: best.t, verified, formats };
}

export function rankMatches(cands: Candidate[], ctx: MatchContext, limit = 3) {
  const excluded: { helperId: string; reason: Exclusion }[] = [];
  const eligible: Match[] = [];
  for (const c of cands) {
    const ex = exclusionFor(c, ctx);
    if (ex) excluded.push({ helperId: c.profile.id, reason: ex });
    else eligible.push(scoreCandidate(c, ctx));
  }
  // Ties broken by id so ordering is stable and nobody is favoured by insertion order.
  eligible.sort((a, b) => b.score - a.score || a.helperId.localeCompare(b.helperId));
  return { matches: eligible.slice(0, limit), eligibleCount: eligible.length, excluded };
}

/** What could be relaxed, with consent, when nobody is eligible. */
export function broadeningOptions(req: HelpRequest, excluded: { reason: Exclusion }[]) {
  const reasons = new Set(excluded.map((e) => e.reason));
  const out: { key: "formats" | "topic" | "timing"; label: string }[] = [];
  if (!req.broadened.includes("formats") && reasons.has("format") && req.formats.length < 3)
    out.push({ key: "formats", label: "Include any format (text, voice or video)" });
  if (!req.broadened.includes("topic") && topicLineage(req.topicId).length > 1 && reasons.has("topic"))
    out.push({ key: "topic", label: `Include people with broader ${getTopic(topicLineage(req.topicId)[0])?.name.toLowerCase()} experience` });
  if (req.timing === "now" && (reasons.has("unavailable") || reasons.has("busy")))
    out.push({ key: "timing", label: "Find a time later instead of right now" });
  return out;
}

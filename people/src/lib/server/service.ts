// All business rules and authorization. Every public method takes the viewer
// resolved on the server and re-checks permissions against stored data — UI
// visibility is never relied on for security.

import {
  assertInvitationTransition, assertRequestTransition, assertSessionTransition, INVITE_TTL_LATER_MS, INVITE_TTL_NOW_MS,
} from "../domain/states";
import { broadeningOptions, rankMatches, type Candidate, type Match } from "../domain/matching";
import { safetyCheck } from "../domain/tagging";
import { getTopic, isHighStakes, rootOf, TOPICS, topicLineage } from "../domain/topics";
import type {
  AvailabilityWindow, Block, ChecklistItem, CredentialReview, ExperienceKind, Feedback, Format, HelpRequest,
  HelperTopic, Intent, Invitation, Message, ModerationAction, ModerationActionKind, Participant, Profile, Report,
  Takeaway, Viewer,
} from "../domain/types";
import { ConflictError, type Repo, type Tx } from "./repo";
import type { ChecklistRow, SessionRow } from "./schema";

export type ErrorCode =
  | "unauthenticated" | "forbidden" | "not_found" | "invalid" | "conflict" | "rate_limited" | "suspended"
  | "expired" | "unavailable" | "not_configured" | "safety";

export class AppError extends Error {
  constructor(public code: ErrorCode, message: string) {
    super(message);
    this.name = "AppError";
  }
}

export const LIMITS = {
  requestsPerHour: 8,
  invitationsPerHour: 15,
  messagesPerMinute: 30,
  reportsPerDay: 10,
  messageLength: 2000,
};

export type TokenMinter = (args: {
  room: string; identity: string; name: string; canPublishVideo: boolean;
}) => Promise<{ token: string; url: string }>;

export interface ServiceDeps {
  repo: Repo;
  now?: () => Date;
  notify?: (topics: string[]) => void;
  mintToken?: TokenMinter | null;
  id?: () => string;
}

export interface PublicProfile {
  id: string;
  displayName: string;
  avatarColor: string;
  intro: string;
  canHelpWith: string;
  curiousAbout: string;
  languages: string[];
  formats: Format[];
  timezone: string;
  locationBroad: string;
  cannotAdvise: string;
  sessionLengthMinutes: number;
  availableNow: boolean;
  topics: HelperTopic[];
  verified: { topicId: string; title: string; issuer: string }[];
  helpedSessions: number;
  addressedCount: number;
  joinedAt: string;
  isModerator: boolean;
}

export interface MatchView extends Match {
  profile: PublicProfile;
}

const AVATAR_COLORS = ["#4f46e5", "#0f766e", "#b45309", "#be185d", "#1d4ed8", "#047857", "#7c3aed", "#9a3412"];
export const avatarColorFor = (id: string) =>
  AVATAR_COLORS[[...id].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % AVATAR_COLORS.length];

const clean = (s: unknown, max: number) => String(s ?? "").trim().slice(0, max);

export class Service {
  repo: Repo;
  now: () => Date;
  notify: (topics: string[]) => void;
  mintToken: TokenMinter | null;
  newId: () => string;

  constructor(deps: ServiceDeps) {
    this.repo = deps.repo;
    this.now = deps.now ?? (() => new Date());
    this.notify = deps.notify ?? (() => undefined);
    this.mintToken = deps.mintToken ?? null;
    this.newId = deps.id ?? (() => crypto.randomUUID());
  }

  private iso(offsetMs = 0) {
    return new Date(this.now().getTime() + offsetMs).toISOString();
  }

  // ───────────────────────── viewer & guards ─────────────────────────

  /** Resolve the viewer from the database; never trust role/status from a cookie or token claim. */
  async viewerFor(userId: string): Promise<{ viewer: Viewer; profile: Profile } | null> {
    return this.repo.tx(async (tx) => {
      const [p] = await tx.select("profiles", { id: userId });
      if (!p) return null;
      return { viewer: { id: p.id, role: p.role, status: p.status }, profile: p };
    });
  }

  private async active(tx: Tx, viewer: Viewer | null): Promise<Profile> {
    if (!viewer) throw new AppError("unauthenticated", "Please sign in.");
    const [p] = await tx.select("profiles", { id: viewer.id });
    if (!p) throw new AppError("unauthenticated", "Please finish setting up your profile.");
    if (p.status !== "active") throw new AppError("suspended", "Your account is suspended. Contact the pilot team.");
    if (!p.onboarded) throw new AppError("forbidden", "Please finish onboarding first.");
    return p;
  }

  private async moderator(tx: Tx, viewer: Viewer | null) {
    const p = await this.active(tx, viewer);
    if (p.role !== "moderator") throw new AppError("forbidden", "Moderators only.");
    return p;
  }

  private async blockedIds(tx: Tx, userId: string) {
    const rows = [
      ...(await tx.select("blocks", { blockerId: userId })),
      ...(await tx.select("blocks", { blockedId: userId })),
    ];
    return new Set(rows.map((b) => (b.blockerId === userId ? b.blockedId : b.blockerId)));
  }

  private async isBlockedPair(tx: Tx, a: string, b: string) {
    return (
      (await tx.count("blocks", { blockerId: a, blockedId: b })) + (await tx.count("blocks", { blockerId: b, blockedId: a })) > 0
    );
  }

  private async rateLimit(tx: Tx, n: number, limit: number, what: string) {
    if (n >= limit) throw new AppError("rate_limited", `You've reached the limit for ${what}. Please try again a little later.`);
  }

  // ───────────────────────── profiles ─────────────────────────

  async saveProfile(
    userId: string,
    input: {
      displayName: string; intro: string; canHelpWith: string; curiousAbout: string; languages: string[];
      formats: Format[]; timezone: string; locationBroad: string; interests: string[]; cannotAdvise: string;
      sessionLengthMinutes: number; adultConfirmed: boolean;
    },
  ) {
    const displayName = clean(input.displayName, 40);
    if (!displayName) throw new AppError("invalid", "Please add a display name.");
    if (!input.adultConfirmed) throw new AppError("invalid", "This pilot is for invited adults (18+) only.");
    const languages = [...new Set(input.languages.map((l) => clean(l, 10)).filter(Boolean))].slice(0, 8);
    if (languages.length === 0) throw new AppError("invalid", "Add at least one language.");
    const formats = (["text", "voice", "video"] as Format[]).filter((f) => input.formats.includes(f));
    if (formats.length === 0) throw new AppError("invalid", "Choose at least one way to talk.");
    const interests = input.interests.filter((t) => getTopic(t) && !isHighStakes(t)).slice(0, 12);
    const fields = {
      displayName, intro: clean(input.intro, 400), canHelpWith: clean(input.canHelpWith, 400),
      curiousAbout: clean(input.curiousAbout, 400), languages, formats, timezone: clean(input.timezone, 60) || "UTC",
      locationBroad: clean(input.locationBroad, 60), interests, cannotAdvise: clean(input.cannotAdvise, 400),
      sessionLengthMinutes: Math.min(120, Math.max(10, Math.round(input.sessionLengthMinutes || 30))),
      adultConfirmed: true, onboarded: true,
    };
    return this.repo.tx(async (tx) => {
      const [existing] = await tx.select("profiles", { id: userId });
      if (existing) {
        if (existing.status !== "active") throw new AppError("suspended", "Your account is suspended.");
        // role and status are never writable here.
        const [p] = await tx.update("profiles", { id: userId }, fields);
        return p;
      }
      return tx.insert("profiles", {
        id: userId, ...fields, avatarColor: avatarColorFor(userId), availableUntil: null, role: "member",
        status: "active", createdAt: this.iso(),
      });
    });
  }

  async setHelperTopics(viewer: Viewer, topics: { topicId: string; kind: ExperienceKind; detail: string; welcomesBeginners: boolean }[]) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const seen = new Set<string>();
      for (const t of topics) {
        if (!getTopic(t.topicId)) throw new AppError("invalid", "Unknown topic.");
        // People can share lived experience, but cannot offer professional advice in high-stakes areas in this pilot.
        if (isHighStakes(t.topicId)) throw new AppError("invalid", "Professional medical, legal and investment advice isn't offered in this pilot.");
        if (!["lived", "professional"].includes(t.kind)) throw new AppError("invalid", "Unknown experience type.");
        if (seen.has(t.topicId)) continue;
        seen.add(t.topicId);
      }
      await tx.delete("helper_topics", { helperId: viewer.id });
      for (const t of topics.filter((x, i, a) => a.findIndex((y) => y.topicId === x.topicId) === i).slice(0, 20)) {
        await tx.insert("helper_topics", {
          helperId: viewer.id, topicId: t.topicId, kind: t.kind, detail: clean(t.detail, 300), welcomesBeginners: !!t.welcomesBeginners,
        });
      }
    });
  }

  async setAvailabilityWindows(viewer: Viewer, windows: Omit<AvailabilityWindow, "id" | "helperId">[]) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      for (const w of windows) {
        if (!(w.weekday >= 0 && w.weekday <= 6 && w.startMinute >= 0 && w.endMinute <= 1440 && w.startMinute < w.endMinute))
          throw new AppError("invalid", "Invalid availability window.");
      }
      await tx.delete("availability_windows", { helperId: viewer.id });
      for (const w of windows.slice(0, 28)) await tx.insert("availability_windows", { id: this.newId(), helperId: viewer.id, ...w });
    });
  }

  /** Presence that ends on its own; helpers are never kept "online" indefinitely. */
  async setAvailableNow(viewer: Viewer, minutes: number) {
    const until = minutes > 0 ? this.iso(Math.min(minutes, 240) * 60_000) : null;
    await this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await tx.update("profiles", { id: viewer.id }, { availableUntil: until });
    });
    return until;
  }

  async submitCredential(viewer: Viewer, input: { topicId: string; title: string; issuer: string; evidenceNote: string }) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      if (!getTopic(input.topicId)) throw new AppError("invalid", "Unknown topic.");
      const title = clean(input.title, 120);
      if (!title) throw new AppError("invalid", "Name the credential.");
      const pending = await tx.count("credential_reviews", { userId: viewer.id, status: "pending" });
      if (pending >= 5) throw new AppError("rate_limited", "You already have several credentials waiting for review.");
      // Always created as pending; only a moderator can change the status.
      return tx.insert("credential_reviews", {
        id: this.newId(), userId: viewer.id, topicId: input.topicId, title, issuer: clean(input.issuer, 120),
        evidenceNote: clean(input.evidenceNote, 600), status: "pending", reviewedBy: null, reviewedAt: null,
        reviewerNote: "", createdAt: this.iso(),
      });
    });
  }

  async myCredentials(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      return tx.select("credential_reviews", { userId: viewer.id }, { orderBy: "createdAt", desc: true });
    });
  }

  async myHelperSetup(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      return {
        topics: await tx.select("helper_topics", { helperId: viewer.id }),
        windows: await tx.select("availability_windows", { helperId: viewer.id }),
      };
    });
  }

  private async publicProfiles(tx: Tx, ids: string[]): Promise<Map<string, PublicProfile>> {
    const out = new Map<string, PublicProfile>();
    if (ids.length === 0) return out;
    const profiles = await tx.select("profiles", { id: ids });
    const topics = await tx.select("helper_topics", { helperId: ids });
    const creds = await tx.select("credential_reviews", { userId: ids, status: "verified" });
    const parts = await tx.select("session_participants", { userId: ids, role: "helper" });
    const ended = new Set(
      (await tx.select("sessions", { id: parts.map((p) => p.sessionId), status: "ended" })).map((s) => s.id),
    );
    const requesterParts = await tx.select("session_participants", { sessionId: [...ended], role: "requester" });
    const now = this.now().getTime();
    for (const p of profiles) {
      const mine = parts.filter((x) => x.userId === p.id && ended.has(x.sessionId));
      const sessionIds = new Set(mine.map((m) => m.sessionId));
      out.set(p.id, {
        id: p.id, displayName: p.displayName, avatarColor: p.avatarColor, intro: p.intro, canHelpWith: p.canHelpWith,
        curiousAbout: p.curiousAbout, languages: p.languages, formats: p.formats, timezone: p.timezone,
        locationBroad: p.locationBroad, cannotAdvise: p.cannotAdvise, sessionLengthMinutes: p.sessionLengthMinutes,
        availableNow: p.status === "active" && !!p.availableUntil && new Date(p.availableUntil).getTime() > now,
        topics: topics.filter((t) => t.helperId === p.id),
        verified: creds.filter((c) => c.userId === p.id).map((c) => ({ topicId: c.topicId, title: c.title, issuer: c.issuer })),
        helpedSessions: mine.length,
        addressedCount: requesterParts.filter((r) => sessionIds.has(r.sessionId) && (r.addressed === "yes" || r.addressed === "partly")).length,
        joinedAt: p.createdAt,
        isModerator: p.role === "moderator",
      });
    }
    return out;
  }

  async getProfile(viewer: Viewer, id: string): Promise<PublicProfile> {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      if (id !== viewer.id && (await this.isBlockedPair(tx, viewer.id, id))) throw new AppError("not_found", "Profile not found.");
      const [target] = await tx.select("profiles", { id });
      if (!target || (target.status !== "active" && viewer.role !== "moderator" && id !== viewer.id))
        throw new AppError("not_found", "Profile not found.");
      return (await this.publicProfiles(tx, [id])).get(id)!;
    });
  }

  /** Private feedback addressed to the viewer (never shown publicly). */
  async myFeedback(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      return tx.select("feedback", { toUser: viewer.id }, { orderBy: "createdAt", desc: true });
    });
  }

  // ───────────────────────── requests ─────────────────────────

  async createRequest(
    viewer: Viewer,
    input: {
      question: string; intent: Intent; topicId: string; tags?: string[]; language: string; formats: Format[];
      timing: "now" | "later"; preferredTime?: string | null; experienceLevel?: HelpRequest["experienceLevel"];
      context?: string; clarificationQuestion?: string; clarificationAnswer?: string; autoMatch?: boolean;
    },
    opts: { followUpOf?: string } = {},
  ) {
    const question = clean(input.question, 600);
    if (question.length < 5) throw new AppError("invalid", "Tell us a little more about what you need.");
    if (!getTopic(input.topicId)) throw new AppError("invalid", "Choose a topic.");
    const safety = safetyCheck(question, input.topicId);
    if (safety.kind === "emergency")
      throw new AppError("safety", "This sounds urgent. People isn't an emergency service — please contact local emergency services now.");
    if (safety.kind === "high_stakes" && isHighStakes(input.topicId))
      throw new AppError("safety", "Professional medical, legal and investment advice isn't available in this pilot.");
    if (!["ask", "learn", "move", "explore"].includes(input.intent)) throw new AppError("invalid", "Choose an intent.");
    // Keep the requester's order: the first format is their preference.
    const formats = [...new Set(input.formats)].filter((f): f is Format => ["text", "voice", "video"].includes(f));
    if (formats.length === 0) throw new AppError("invalid", "Choose at least one format.");
    let preferredTime: string | null = null;
    if (input.timing === "later") {
      if (!input.preferredTime || isNaN(Date.parse(input.preferredTime))) throw new AppError("invalid", "Pick a time.");
      preferredTime = new Date(input.preferredTime).toISOString();
      if (Date.parse(preferredTime) < this.now().getTime()) throw new AppError("invalid", "Pick a time in the future.");
    }
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const recent = await tx.count("requests", { requesterId: viewer.id, createdAt: { gt: this.iso(-3600_000) } });
      await this.rateLimit(tx, recent, LIMITS.requestsPerHour, "new requests");
      const req = await tx.insert("requests", {
        id: this.newId(), requesterId: viewer.id, question, intent: input.intent, topicId: input.topicId,
        tags: (input.tags ?? []).map((t) => clean(t, 40)).slice(0, 8), language: clean(input.language, 10) || "en",
        formats, timing: input.timing, preferredTime, experienceLevel: input.experienceLevel ?? "",
        context: clean(input.context, 800), clarificationQuestion: clean(input.clarificationQuestion, 200),
        clarificationAnswer: clean(input.clarificationAnswer, 400), broadened: [], status: "open",
        autoMatch: !!input.autoMatch, followUpOf: opts.followUpOf ?? null, createdAt: this.iso(),
      });
      if (req.autoMatch) await this.autoInvite(tx, req);
      return req;
    });
  }

  private async requireOwnRequest(tx: Tx, viewer: Viewer, requestId: string, lock = false) {
    const [req] = await tx.select("requests", { id: requestId }, { forUpdate: lock });
    if (!req || req.requesterId !== viewer.id) throw new AppError("not_found", "Request not found.");
    return req;
  }

  private async setRequestStatus(tx: Tx, req: HelpRequest, to: HelpRequest["status"]) {
    if (req.status === to) return req;
    assertRequestTransition(req.status, to);
    const [r] = await tx.update("requests", { id: req.id, status: req.status }, { status: to });
    if (!r) throw new AppError("conflict", "This request changed. Please refresh.");
    req.status = to;
    return r;
  }

  private async candidates(tx: Tx, req: HelpRequest): Promise<Candidate[]> {
    const root = rootOf(req.topicId);
    const related = TOPICS.filter((t) => rootOf(t.id) === root).map((t) => t.id);
    const helperTopics = await tx.select("helper_topics", { topicId: related });
    const ids = [...new Set(helperTopics.map((t) => t.helperId))];
    if (ids.length === 0) return [];
    const profiles = await tx.select("profiles", { id: ids });
    const windows = await tx.select("availability_windows", { helperId: ids });
    const creds = await tx.select("credential_reviews", { userId: ids, status: "verified" });
    const parts = await tx.select("session_participants", { userId: ids });
    const sessions = await tx.select("sessions", { id: parts.map((p) => p.sessionId) });
    const fb = await tx.select("feedback", { toUser: ids });
    const fbSessions = new Map(sessions.map((s) => [s.id, s]));
    const fbRequests = new Map(
      (await tx.select("requests", { id: [...new Set(fb.map((f) => fbSessions.get(f.sessionId)?.requestId).filter(Boolean) as string[])] })).map((r) => [r.id, r]),
    );
    return profiles.map((profile) => {
      const mySessions = parts.filter((p) => p.userId === profile.id).map((p) => fbSessions.get(p.sessionId)!).filter(Boolean);
      const busy = this.isBusy(mySessions, req.timing === "now" ? null : req.preferredTime, profile.sessionLengthMinutes);
      const relevant = fb.filter((f) => {
        const s = fbSessions.get(f.sessionId);
        const r = s && fbRequests.get(s.requestId);
        return f.toUser === profile.id && r && rootOf(r.topicId) === root;
      });
      return {
        profile,
        topics: helperTopics.filter((t) => t.helperId === profile.id),
        verifiedTopicIds: creds.filter((c) => c.userId === profile.id).map((c) => c.topicId),
        windows: windows.filter((w) => w.helperId === profile.id),
        busy,
        feedback: {
          count: relevant.length,
          avgHelpful: relevant.length ? relevant.reduce((a, f) => a + f.helpful, 0) / relevant.length : 0,
        },
      };
    });
  }

  /** "now" → in an active session. Scheduled → another booking overlaps the slot. */
  private isBusy(sessions: SessionRow[], at: string | null, lengthMin: number) {
    if (at === null) return sessions.some((s) => s.status === "active");
    const t = Date.parse(at);
    const span = Math.max(lengthMin, 30) * 60_000;
    return sessions.some((s) => s.status === "scheduled" && s.scheduledAt && Math.abs(Date.parse(s.scheduledAt) - t) < span);
  }

  private async rank(tx: Tx, req: HelpRequest, limit: number) {
    const invited = await tx.select("invitations", { requestId: req.id });
    return rankMatches(await this.candidates(tx, req), {
      request: req,
      now: this.now(),
      blockedIds: await this.blockedIds(tx, req.requesterId),
      alreadyInvited: new Set(invited.map((i) => i.helperId)),
    }, limit);
  }

  async findMatches(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      const req = await this.requireOwnRequest(tx, viewer, requestId);
      if (isHighStakes(req.topicId)) return { matches: [] as MatchView[], eligibleCount: 0, broaden: [] };
      const { matches, eligibleCount, excluded } = await this.rank(tx, req, 3);
      const profiles = await this.publicProfiles(tx, matches.map((m) => m.helperId));
      return {
        matches: matches.map((m) => ({ ...m, profile: profiles.get(m.helperId)! })),
        eligibleCount,
        broaden: broadeningOptions(req, excluded),
      };
    });
  }

  private async createInvitation(tx: Tx, req: HelpRequest, helperId: string, auto: boolean) {
    const recent = await tx.count("invitations", { requesterId: req.requesterId, createdAt: { gt: this.iso(-3600_000) } });
    await this.rateLimit(tx, recent, LIMITS.invitationsPerHour, "invitations");
    const ttl = req.timing === "now" ? INVITE_TTL_NOW_MS : INVITE_TTL_LATER_MS;
    let inv: Invitation;
    try {
      inv = await tx.insert("invitations", {
        id: this.newId(), requestId: req.id, requesterId: req.requesterId, helperId, status: "pending", auto,
        proposedTime: req.timing === "later" ? req.preferredTime : null,
        // An invitation for a later time must still be answered before that time.
        expiresAt: req.preferredTime ? new Date(Math.min(this.now().getTime() + ttl, Date.parse(req.preferredTime))).toISOString() : this.iso(ttl),
        respondedAt: null, createdAt: this.iso(),
      });
    } catch (e) {
      if (e instanceof ConflictError) throw new AppError("conflict", "You're already waiting on a reply for this request.");
      throw e;
    }
    await this.setRequestStatus(tx, req, "waiting");
    this.notify([`user:${helperId}`, `user:${req.requesterId}`]);
    return inv;
  }

  async inviteHelper(viewer: Viewer, requestId: string, helperId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      const req = await this.requireOwnRequest(tx, viewer, requestId, true);
      if (!["open", "async_open", "answered"].includes(req.status))
        throw new AppError("conflict", req.status === "waiting" ? "You're already waiting on a reply." : "This request is no longer open.");
      // Re-run eligibility for this specific helper; the client's list is never trusted.
      const { matches } = await this.rank(tx, req, 1000);
      let ok = matches.some((m) => m.helperId === helperId);
      // Someone who already wrote an answer to a "later" question may be invited to talk, subject to blocks and status.
      if (!ok && req.status === "answered") {
        const responded = await tx.count("async_responses", { requestId, helperId });
        const [h] = await tx.select("profiles", { id: helperId });
        ok = responded > 0 && !!h && h.status === "active" && !(await this.isBlockedPair(tx, viewer.id, helperId))
          && (await tx.count("invitations", { requestId, helperId })) === 0;
      }
      if (!ok) throw new AppError("unavailable", "That person isn't available for this request right now.");
      return this.createInvitation(tx, req, helperId, false);
    });
  }

  private async autoInvite(tx: Tx, req: HelpRequest) {
    const { matches } = await this.rank(tx, req, 1);
    if (matches.length === 0) return null;
    return this.createInvitation(tx, req, matches[0].helperId, true);
  }

  async startAutoMatch(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      const req = await this.requireOwnRequest(tx, viewer, requestId, true);
      if (!["open", "async_open", "answered"].includes(req.status)) throw new AppError("conflict", "This request is not open.");
      await tx.update("requests", { id: req.id }, { autoMatch: true });
      req.autoMatch = true;
      const inv = await this.autoInvite(tx, req);
      if (!inv) throw new AppError("unavailable", "Nobody eligible is available right now.");
      return inv;
    });
  }

  async broaden(viewer: Viewer, requestId: string, key: "formats" | "topic" | "timing", preferredTime?: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const req = await this.requireOwnRequest(tx, viewer, requestId, true);
      if (!["open", "async_open", "answered"].includes(req.status)) throw new AppError("conflict", "This request is not open.");
      if (key === "timing") {
        if (!preferredTime || isNaN(Date.parse(preferredTime)) || Date.parse(preferredTime) < this.now().getTime())
          throw new AppError("invalid", "Pick a time in the future.");
        await tx.update("requests", { id: req.id }, { timing: "later", preferredTime: new Date(preferredTime).toISOString() });
      } else if (!req.broadened.includes(key)) {
        await tx.update("requests", { id: req.id }, { broadened: [...req.broadened, key] });
      }
    });
  }

  async leaveForLater(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const req = await this.requireOwnRequest(tx, viewer, requestId, true);
      await this.setRequestStatus(tx, req, "async_open");
    });
  }

  async cancelRequest(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const req = await this.requireOwnRequest(tx, viewer, requestId, true);
      const pending = await tx.select("invitations", { requestId, status: "pending" }, { forUpdate: true });
      for (const inv of pending) {
        await tx.update("invitations", { id: inv.id }, { status: "cancelled", respondedAt: this.iso() });
        this.notify([`user:${inv.helperId}`]);
      }
      if (req.status === "waiting") await this.setRequestStatus(tx, req, "open");
      await this.setRequestStatus(tx, req, "cancelled");
    });
  }

  /** Withdraw a pending invitation but keep the request open. */
  async cancelInvitation(viewer: Viewer, invitationId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const [inv] = await tx.select("invitations", { id: invitationId }, { forUpdate: true });
      if (!inv || inv.requesterId !== viewer.id) throw new AppError("not_found", "Invitation not found.");
      if (inv.status !== "pending") throw new AppError("conflict", "That invitation was already answered.");
      await tx.update("invitations", { id: inv.id }, { status: "cancelled", respondedAt: this.iso() });
      const [req] = await tx.select("requests", { id: inv.requestId }, { forUpdate: true });
      await tx.update("requests", { id: req.id }, { autoMatch: false });
      if (req.status === "waiting") await this.setRequestStatus(tx, req, "open");
      this.notify([`user:${inv.helperId}`, `user:${inv.requesterId}`]);
    });
  }

  /**
   * Expire unanswered invitations. Runs lazily inside the transactions that read
   * invitations, so state is correct without a background worker.
   */
  async expireStale(tx: Tx) {
    const stale = await tx.select("invitations", { status: "pending", expiresAt: { lt: this.iso() } }, { forUpdate: true });
    for (const inv of stale) {
      await tx.update("invitations", { id: inv.id, status: "pending" }, { status: "expired" });
      const [req] = await tx.select("requests", { id: inv.requestId }, { forUpdate: true });
      if (req?.status === "waiting") {
        await this.setRequestStatus(tx, req, "open");
        if (req.autoMatch) await this.autoInvite(tx, req);
      }
      this.notify([`user:${inv.helperId}`, `user:${inv.requesterId}`]);
    }
  }

  async getRequest(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      const req = await this.requireOwnRequest(tx, viewer, requestId);
      const invitations = await tx.select("invitations", { requestId }, { orderBy: "createdAt" });
      const [session] = await tx.select("sessions", { requestId });
      const responses = await tx.select("async_responses", { requestId }, { orderBy: "createdAt" });
      const profiles = await this.publicProfiles(tx, [...new Set([...invitations.map((i) => i.helperId), ...responses.map((r) => r.helperId)])]);
      // Hide people who have since blocked (or been blocked by) the viewer.
      const blocked = await this.blockedIds(tx, viewer.id);
      return {
        request: req,
        invitations: invitations.map((i) => ({ ...i, helper: blocked.has(i.helperId) ? null : profiles.get(i.helperId) ?? null })),
        session: session ?? null,
        responses: responses.filter((r) => !blocked.has(r.helperId)).map((r) => ({ ...r, helper: profiles.get(r.helperId) ?? null })),
      };
    });
  }

  async listMyRequests(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      return tx.select("requests", { requesterId: viewer.id }, { orderBy: "createdAt", desc: true, limit: 50 });
    });
  }

  // ───────────────────────── helper side ─────────────────────────

  async respondInvitation(viewer: Viewer, invitationId: string, accept: boolean) {
    return this.repo.tx(async (tx) => {
      const helper = await this.active(tx, viewer);
      const [inv] = await tx.select("invitations", { id: invitationId }, { forUpdate: true });
      if (!inv || inv.helperId !== viewer.id) throw new AppError("not_found", "Invitation not found.");
      if (inv.status !== "pending") {
        const msg: Record<string, string> = {
          accepted: "You already accepted this.", declined: "You already declined this.", expired: "This invitation expired.",
          cancelled: "They withdrew this request.", unavailable: "This invitation is no longer available.",
        };
        throw new AppError(inv.status === "expired" ? "expired" : "conflict", msg[inv.status]);
      }
      const [req] = await tx.select("requests", { id: inv.requestId }, { forUpdate: true });
      if (Date.parse(inv.expiresAt) <= this.now().getTime()) {
        await tx.update("invitations", { id: inv.id }, { status: "expired" });
        if (req.status === "waiting") {
          await this.setRequestStatus(tx, req, "open");
          if (req.autoMatch) await this.autoInvite(tx, req);
        }
        this.notify([`user:${inv.requesterId}`]);
        return { status: "expired" as const };
      }
      if (!accept) {
        assertInvitationTransition("pending", "declined");
        await tx.update("invitations", { id: inv.id }, { status: "declined", respondedAt: this.iso() });
        await this.setRequestStatus(tx, req, "open");
        if (req.autoMatch) await this.autoInvite(tx, req);
        this.notify([`user:${inv.requesterId}`]);
        return { status: "declined" as const };
      }

      // Lock both people's profiles in a stable order so concurrent accepts serialise without deadlock.
      const ids = [inv.helperId, inv.requesterId].sort();
      const locked = await tx.select("profiles", { id: ids }, { forUpdate: true, orderBy: "id" });
      const requester = locked.find((p) => p.id === inv.requesterId);
      const markUnavailable = async (why: string) => {
        await tx.update("invitations", { id: inv.id }, { status: "unavailable", respondedAt: this.iso() });
        await this.setRequestStatus(tx, req, "open");
        this.notify([`user:${inv.requesterId}`]);
        return { status: "unavailable" as const, reason: why };
      };
      if (!requester || requester.status !== "active" || req.status !== "waiting") return markUnavailable("The request is no longer open.");
      if (await this.isBlockedPair(tx, inv.helperId, inv.requesterId)) return markUnavailable("This request is no longer available.");

      // Double-booking guard, re-checked under lock.
      for (const who of [helper, requester]) {
        const parts = await tx.select("session_participants", { userId: who.id });
        const sessions = await tx.select("sessions", { id: parts.map((p) => p.sessionId), status: ["active", "scheduled"] });
        if (this.isBusy(sessions, inv.proposedTime, Math.max(helper.sessionLengthMinutes, 30)))
          throw new AppError("conflict", who.id === helper.id ? "You're already in a session at that time." : "They're already in another session at that time.");
      }

      assertInvitationTransition("pending", "accepted");
      await tx.update("invitations", { id: inv.id }, { status: "accepted", respondedAt: this.iso() });
      await this.setRequestStatus(tx, req, "matched");
      const sessionId = this.newId();
      const scheduled = !!inv.proposedTime && Date.parse(inv.proposedTime) > this.now().getTime() + 10 * 60_000;
      const format: Format = req.formats.find((f) => helper.formats.includes(f)) ?? "text";
      await tx.insert("sessions", {
        id: sessionId, requestId: req.id, status: scheduled ? "scheduled" : "active", goal: req.question, format,
        scheduledAt: inv.proposedTime, startedAt: scheduled ? null : this.iso(), endedAt: null,
        roomName: `people-${crypto.randomUUID()}`, createdAt: this.iso(), timerEndsAt: null, timerLabel: "",
      });
      for (const [userId, role] of [[req.requesterId, "requester"], [inv.helperId, "helper"]] as const) {
        await tx.insert("session_participants", {
          sessionId, userId, role, videoOptIn: false, keepGoing: false, reconnectOptIn: false, addressed: "", leftAt: null,
        });
      }
      await tx.insert("shared_notes", { sessionId, body: "", updatedBy: null, updatedAt: this.iso() });
      await tx.insert("messages", {
        id: this.newId(), sessionId, senderId: null, createdAt: this.iso(),
        body: scheduled ? "Session booked. You can chat here before it starts." : "You're connected. Say hello and agree on what would make this useful.",
      });
      this.notify([`user:${inv.requesterId}`, `user:${inv.helperId}`]);
      return { status: "accepted" as const, sessionId };
    });
  }

  async inbox(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      const me = await this.active(tx, viewer);
      await this.expireStale(tx);
      const pending = await tx.select("invitations", { helperId: viewer.id, status: "pending" }, { orderBy: "createdAt" });
      const reqs = await tx.select("requests", { id: pending.map((p) => p.requestId) });
      const requesters = await this.publicProfiles(tx, pending.map((p) => p.requesterId));
      const recent = await tx.select("invitations", { helperId: viewer.id, status: ["expired", "cancelled", "unavailable"] }, { orderBy: "createdAt", desc: true, limit: 5 });

      // Async questions this person could answer: topic + language fit, not blocked, not their own.
      const myTopics = await tx.select("helper_topics", { helperId: viewer.id });
      const blocked = await this.blockedIds(tx, viewer.id);
      const openAsync = (await tx.select("requests", { status: ["async_open", "answered"] }, { orderBy: "createdAt", desc: true, limit: 100 }))
        .filter((r) => r.requesterId !== viewer.id && !blocked.has(r.requesterId))
        .filter((r) => myTopics.some((t) => topicLineage(t.topicId).length >= 1 && sharedDepth(t.topicId, r.topicId) >= Math.min(2, topicLineage(r.topicId).length)))
        .filter((r) => me.languages.some((l) => l.split("-")[0] === r.language.split("-")[0]));
      const answered = await tx.select("async_responses", { helperId: viewer.id, requestId: openAsync.map((r) => r.id) });
      const askerNames = await this.publicProfiles(tx, openAsync.map((r) => r.requesterId));

      const parts = await tx.select("session_participants", { userId: viewer.id });
      const sessions = await tx.select("sessions", { id: parts.map((p) => p.sessionId), status: ["scheduled", "active"] }, { orderBy: "scheduledAt" });
      const sessReqs = await tx.select("requests", { id: sessions.map((s) => s.requestId) });

      return {
        availableUntil: me.availableUntil,
        invitations: pending.map((inv) => ({
          invitation: inv,
          request: reqs.find((r) => r.id === inv.requestId)!,
          requester: requesters.get(inv.requesterId) ?? null,
        })),
        recent,
        asyncQuestions: openAsync.slice(0, 20).map((r) => ({
          request: r, asker: askerNames.get(r.requesterId) ?? null, answeredByMe: answered.some((a) => a.requestId === r.id),
        })),
        sessions: sessions.map((s) => ({ session: s, request: sessReqs.find((r) => r.id === s.requestId)! })),
      };
    });
  }

  /** Lightweight counts for navigation badges. */
  async badges(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.expireStale(tx);
      const invites = await tx.count("invitations", { helperId: viewer.id, status: "pending" });
      const parts = await tx.select("session_participants", { userId: viewer.id });
      const live = await tx.count("sessions", { id: parts.map((p) => p.sessionId), status: "active" });
      return { invites, live };
    });
  }

  async getAsyncQuestion(viewer: Viewer, requestId: string) {
    return this.repo.tx(async (tx) => {
      const me = await this.active(tx, viewer);
      const [req] = await tx.select("requests", { id: requestId });
      if (!req || !["async_open", "answered"].includes(req.status) || req.requesterId === viewer.id) throw new AppError("not_found", "Question not found.");
      if (await this.isBlockedPair(tx, viewer.id, req.requesterId)) throw new AppError("not_found", "Question not found.");
      const myTopics = await tx.select("helper_topics", { helperId: viewer.id });
      const fits = myTopics.some((t) => sharedDepth(t.topicId, req.topicId) >= Math.min(2, topicLineage(req.topicId).length))
        && me.languages.some((l) => l.split("-")[0] === req.language.split("-")[0]);
      if (!fits) throw new AppError("not_found", "Question not found.");
      const mine = await tx.select("async_responses", { requestId, helperId: viewer.id });
      return { request: req, myResponses: mine };
    });
  }

  async respondAsync(viewer: Viewer, requestId: string, body: string) {
    const text = clean(body, 3000);
    if (text.length < 2) throw new AppError("invalid", "Write a response first.");
    await this.getAsyncQuestion(viewer, requestId); // authorization
    return this.repo.tx(async (tx) => {
      const recent = await tx.count("async_responses", { helperId: viewer.id, createdAt: { gt: this.iso(-3600_000) } });
      await this.rateLimit(tx, recent, 20, "written answers");
      const [req] = await tx.select("requests", { id: requestId }, { forUpdate: true });
      const r = await tx.insert("async_responses", { id: this.newId(), requestId, helperId: viewer.id, body: text, createdAt: this.iso() });
      if (req.status === "async_open") await this.setRequestStatus(tx, req, "answered");
      this.notify([`user:${req.requesterId}`]);
      return r;
    });
  }

  // ───────────────────────── sessions ─────────────────────────

  private async membership(tx: Tx, viewer: Viewer, sessionId: string) {
    const parts = await tx.select("session_participants", { sessionId });
    const me = parts.find((p) => p.userId === viewer.id);
    // Same response whether the session doesn't exist or the viewer isn't in it.
    if (!me) throw new AppError("not_found", "Session not found.");
    const [session] = await tx.select("sessions", { id: sessionId });
    const other = parts.find((p) => p.userId !== viewer.id)!;
    return { session, me, other, parts };
  }

  async getSession(viewer: Viewer, sessionId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const { session, me, other } = await this.membership(tx, viewer, sessionId);
      const [request] = await tx.select("requests", { id: session.requestId });
      const profiles = await this.publicProfiles(tx, [me.userId, other.userId]);
      const [note] = await tx.select("shared_notes", { sessionId });
      const [priv] = await tx.select("private_notes", { sessionId, userId: viewer.id });
      const iBlocked = (await tx.count("blocks", { blockerId: viewer.id, blockedId: other.userId })) > 0;
      const blockedEither = await this.isBlockedPair(tx, viewer.id, other.userId);
      const myFeedback = await tx.count("feedback", { sessionId, fromUser: viewer.id });
      return {
        session,
        request,
        me,
        other: { ...other, profile: profiles.get(other.userId)! },
        myProfile: profiles.get(me.userId)!,
        messages: await tx.select("messages", { sessionId }, { orderBy: "createdAt" }),
        checklist: (await tx.select("checklist_items", { sessionId }, { orderBy: "createdAt" })) as ChecklistRow[],
        sharedNote: note ?? { sessionId, body: "", updatedBy: null, updatedAt: session.createdAt },
        privateNote: priv?.body ?? "",
        iBlocked,
        blocked: blockedEither,
        feedbackGiven: myFeedback > 0,
        videoAllowed: me.videoOptIn && other.videoOptIn,
        keepGoingBoth: me.keepGoing && other.keepGoing,
        reconnectBoth: me.reconnectOptIn && other.reconnectOptIn,
      };
    });
  }

  private async liveSession(tx: Tx, viewer: Viewer, sessionId: string, allow: SessionRow["status"][] = ["active"]) {
    await this.active(tx, viewer);
    const m = await this.membership(tx, viewer, sessionId);
    if (!allow.includes(m.session.status)) throw new AppError("conflict", m.session.status === "ended" ? "This session has ended." : "This session isn't active.");
    if (await this.isBlockedPair(tx, viewer.id, m.other.userId)) throw new AppError("forbidden", "This conversation is closed.");
    return m;
  }

  async startSession(viewer: Viewer, sessionId: string) {
    return this.repo.tx(async (tx) => {
      const { session } = await this.liveSession(tx, viewer, sessionId, ["scheduled"]);
      if (session.scheduledAt && Date.parse(session.scheduledAt) - this.now().getTime() > 10 * 60_000)
        throw new AppError("conflict", "You can start up to 10 minutes before the agreed time.");
      assertSessionTransition("scheduled", "active");
      await tx.update("sessions", { id: sessionId, status: "scheduled" }, { status: "active", startedAt: this.iso() });
      this.notify([`session:${sessionId}`]);
    });
  }

  async sendMessage(viewer: Viewer, sessionId: string, body: string) {
    const text = clean(body, LIMITS.messageLength);
    if (!text) throw new AppError("invalid", "Message is empty.");
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      const recent = await tx.count("messages", { senderId: viewer.id, createdAt: { gt: this.iso(-60_000) } });
      await this.rateLimit(tx, recent, LIMITS.messagesPerMinute, "messages");
      const m = await tx.insert("messages", { id: this.newId(), sessionId, senderId: viewer.id, body: text, createdAt: this.iso() });
      this.notify([`session:${sessionId}`]);
      return m;
    });
  }

  async addChecklistItem(viewer: Viewer, sessionId: string, text: string, kind: ChecklistRow["kind"] = "task") {
    const t = clean(text, 200);
    if (!t) throw new AppError("invalid", "Item is empty.");
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      if ((await tx.count("checklist_items", { sessionId })) >= 30) throw new AppError("rate_limited", "That's a long list — try finishing a few first.");
      const item = await tx.insert("checklist_items", {
        id: this.newId(), sessionId, text: t, done: false, createdBy: viewer.id, createdAt: this.iso(),
        kind: ["step", "try", "task"].includes(kind) ? kind : "task",
      });
      this.notify([`session:${sessionId}`]);
      return item;
    });
  }

  async toggleChecklistItem(viewer: Viewer, sessionId: string, itemId: string, done: boolean) {
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      const rows = await tx.update("checklist_items", { id: itemId, sessionId }, { done });
      if (!rows.length) throw new AppError("not_found", "Item not found.");
      this.notify([`session:${sessionId}`]);
    });
  }

  async removeChecklistItem(viewer: Viewer, sessionId: string, itemId: string) {
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      await tx.delete("checklist_items", { id: itemId, sessionId });
      this.notify([`session:${sessionId}`]);
    });
  }

  async updateSharedNote(viewer: Viewer, sessionId: string, body: string) {
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled", "ended"]);
      await tx.update("shared_notes", { sessionId }, { body: clean(body, 8000), updatedBy: viewer.id, updatedAt: this.iso() });
      this.notify([`session:${sessionId}`]);
    });
  }

  async updatePrivateNote(viewer: Viewer, sessionId: string, body: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await this.membership(tx, viewer, sessionId);
      const patch = { body: clean(body, 8000), updatedAt: this.iso() };
      const rows = await tx.update("private_notes", { sessionId, userId: viewer.id }, patch);
      if (!rows.length) await tx.insert("private_notes", { sessionId, userId: viewer.id, ...patch });
      // No notify: private notes are never broadcast.
    });
  }

  async setGoal(viewer: Viewer, sessionId: string, goal: string) {
    const g = clean(goal, 300);
    if (!g) throw new AppError("invalid", "Goal is empty.");
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      await tx.update("sessions", { id: sessionId }, { goal: g });
      this.notify([`session:${sessionId}`]);
    });
  }

  async setParticipantFlag(viewer: Viewer, sessionId: string, flag: "videoOptIn" | "keepGoing", value: boolean) {
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId, ["active", "scheduled"]);
      await tx.update("session_participants", { sessionId, userId: viewer.id }, { [flag]: value } as Partial<Participant>);
      this.notify([`session:${sessionId}`]);
    });
  }

  async setTimer(viewer: Viewer, sessionId: string, minutes: number, label: string) {
    return this.repo.tx(async (tx) => {
      await this.liveSession(tx, viewer, sessionId);
      const m = Math.round(minutes);
      if (m !== 0 && (m < 1 || m > 90)) throw new AppError("invalid", "Timers run from 1 to 90 minutes.");
      await tx.update("sessions", { id: sessionId }, m === 0 ? { timerEndsAt: null, timerLabel: "" } : { timerEndsAt: this.iso(m * 60_000), timerLabel: clean(label, 60) });
      this.notify([`session:${sessionId}`]);
    });
  }

  async endSession(viewer: Viewer, sessionId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const { session } = await this.membership(tx, viewer, sessionId);
      await this.closeSession(tx, session, viewer.id, "ended the session");
    });
  }

  private async closeSession(tx: Tx, session: SessionRow, byUserId: string | null, verb: string) {
    const [fresh] = await tx.select("sessions", { id: session.id }, { forUpdate: true });
    if (fresh.status === "ended" || fresh.status === "cancelled") return;
    const to = fresh.status === "scheduled" ? "cancelled" : "ended";
    assertSessionTransition(fresh.status, to);
    await tx.update("sessions", { id: session.id }, { status: to, endedAt: this.iso(), timerEndsAt: null });
    await tx.update("session_participants", { sessionId: session.id, leftAt: { isNull: true } }, { leftAt: this.iso() });
    const [req] = await tx.select("requests", { id: fresh.requestId }, { forUpdate: true });
    if (req?.status === "matched") await this.setRequestStatus(tx, req, "closed");
    let who = "";
    if (byUserId) {
      const [p] = await tx.select("profiles", { id: byUserId });
      who = p?.displayName ?? "";
    }
    await tx.insert("messages", {
      id: this.newId(), sessionId: session.id, senderId: null, createdAt: this.iso(),
      body: who ? `${who} ${verb}.` : `This session was ${verb}.`,
    });
    this.notify([`session:${session.id}`]);
  }

  /**
   * Short-lived LiveKit token, only for verified participants of an active,
   * unblocked session. Camera publishing is granted only after both opt in.
   */
  async callToken(viewer: Viewer, sessionId: string) {
    if (!this.mintToken) throw new AppError("not_configured", "Voice and video aren't configured on this server.");
    const { session, me, other, myName } = await this.repo.tx(async (tx) => {
      const p = await this.active(tx, viewer);
      const m = await this.liveSession(tx, viewer, sessionId);
      const [o] = await tx.select("profiles", { id: m.other.userId });
      if (!o || o.status !== "active") throw new AppError("unavailable", "The other person is no longer available.");
      if (m.session.format === "text") throw new AppError("forbidden", "This session was agreed as text-only.");
      return { ...m, myName: p.displayName };
    });
    const canPublishVideo = session.format === "video" && me.videoOptIn && other.videoOptIn;
    const t = await this.mintToken({ room: session.roomName, identity: viewer.id, name: myName, canPublishVideo });
    return { ...t, canPublishVideo };
  }

  async wrapUp(
    viewer: Viewer,
    sessionId: string,
    input: { addressed: Participant["addressed"]; reconnect: boolean; helpful?: number; respectful?: boolean; comment?: string },
  ) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const { session, other } = await this.membership(tx, viewer, sessionId);
      if (session.status !== "ended") throw new AppError("conflict", "End the session first.");
      if (!["", "yes", "partly", "no"].includes(input.addressed)) throw new AppError("invalid", "Invalid answer.");
      const blocked = await this.isBlockedPair(tx, viewer.id, other.userId);
      await tx.update("session_participants", { sessionId, userId: viewer.id }, {
        addressed: input.addressed, reconnectOptIn: blocked ? false : !!input.reconnect,
      });
      if (input.helpful != null) {
        const h = Math.round(input.helpful);
        if (h < 1 || h > 5) throw new AppError("invalid", "Rating must be 1–5.");
        try {
          await tx.insert("feedback", {
            id: this.newId(), sessionId, fromUser: viewer.id, toUser: other.userId, helpful: h,
            respectful: input.respectful !== false, comment: clean(input.comment, 1000), createdAt: this.iso(),
          });
        } catch (e) {
          if (e instanceof ConflictError) throw new AppError("conflict", "You already left feedback for this session.");
          throw e;
        }
      }
      this.notify([`session:${sessionId}`]);
    });
  }

  async requestFollowUp(viewer: Viewer, sessionId: string, input: { question: string; timing: "now" | "later"; preferredTime?: string }) {
    const { other, request } = await this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const m = await this.membership(tx, viewer, sessionId);
      if (m.session.status !== "ended") throw new AppError("conflict", "The session hasn't ended.");
      if (!m.me.reconnectOptIn || !m.other.reconnectOptIn) throw new AppError("forbidden", "Both people need to opt in to reconnect.");
      if (await this.isBlockedPair(tx, viewer.id, m.other.userId)) throw new AppError("forbidden", "Reconnecting isn't available.");
      const [request] = await tx.select("requests", { id: m.session.requestId });
      return { other: m.other, request };
    });
    const created = await this.createRequest(viewer, {
      question: input.question, intent: request.intent, topicId: request.topicId, language: request.language,
      formats: request.formats, timing: input.timing, preferredTime: input.preferredTime ?? null,
      context: `Follow-up to an earlier session.`,
    }, { followUpOf: sessionId });
    // Direct invitation — no public contact details are ever exchanged.
    const inv = await this.repo.tx(async (tx) => {
      const [req] = await tx.select("requests", { id: created.id }, { forUpdate: true });
      const [o] = await tx.select("profiles", { id: other.userId });
      if (!o || o.status !== "active") throw new AppError("unavailable", "They're not available right now.");
      return this.createInvitation(tx, req, other.userId, false);
    });
    return { request: created, invitation: inv };
  }

  async listMySessions(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const parts = await tx.select("session_participants", { userId: viewer.id });
      const sessions = await tx.select("sessions", { id: parts.map((p) => p.sessionId) }, { orderBy: "createdAt", desc: true });
      const reqs = await tx.select("requests", { id: sessions.map((s) => s.requestId) });
      const allParts = await tx.select("session_participants", { sessionId: sessions.map((s) => s.id) });
      const others = await this.publicProfiles(tx, [...new Set(allParts.filter((p) => p.userId !== viewer.id).map((p) => p.userId))]);
      return sessions.map((s) => {
        const other = allParts.find((p) => p.sessionId === s.id && p.userId !== viewer.id)!;
        const me = allParts.find((p) => p.sessionId === s.id && p.userId === viewer.id)!;
        return { session: s, request: reqs.find((r) => r.id === s.requestId)!, me, other: others.get(other.userId) ?? null, otherRole: other.role };
      });
    });
  }

  // ───────────────────────── learning ─────────────────────────

  async listTakeaways(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      return tx.select("takeaways", { userId: viewer.id }, { orderBy: "createdAt", desc: true });
    });
  }

  async addTakeaway(viewer: Viewer, input: { sessionId?: string | null; title: string; body: string; nextSteps: string }) {
    const title = clean(input.title, 120);
    if (!title) throw new AppError("invalid", "Give it a short title.");
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      if (input.sessionId) await this.membership(tx, viewer, input.sessionId);
      return tx.insert("takeaways", {
        id: this.newId(), userId: viewer.id, sessionId: input.sessionId ?? null, title, body: clean(input.body, 8000),
        nextSteps: clean(input.nextSteps, 2000), createdAt: this.iso(),
      });
    });
  }

  async deleteTakeaway(viewer: Viewer, id: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const n = await tx.delete("takeaways", { id, userId: viewer.id });
      if (!n) throw new AppError("not_found", "Not found.");
    });
  }

  // ───────────────────────── safety ─────────────────────────

  async block(viewer: Viewer, userId: string) {
    if (userId === viewer.id) throw new AppError("invalid", "You can't block yourself.");
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const [target] = await tx.select("profiles", { id: userId });
      if (!target) throw new AppError("not_found", "Person not found.");
      if ((await tx.count("blocks", { blockerId: viewer.id, blockedId: userId })) === 0)
        await tx.insert("blocks", { blockerId: viewer.id, blockedId: userId, createdAt: this.iso() });
      // Withdraw anything pending between the two people.
      for (const [a, b] of [[viewer.id, userId], [userId, viewer.id]]) {
        const pend = await tx.select("invitations", { requesterId: a, helperId: b, status: "pending" }, { forUpdate: true });
        for (const inv of pend) {
          await tx.update("invitations", { id: inv.id }, { status: inv.helperId === viewer.id ? "cancelled" : "unavailable", respondedAt: this.iso() });
          const [req] = await tx.select("requests", { id: inv.requestId }, { forUpdate: true });
          if (req.status === "waiting") await this.setRequestStatus(tx, req, "open");
        }
      }
      // End live or upcoming sessions between them immediately.
      const mine = await tx.select("session_participants", { userId: viewer.id });
      const theirs = await tx.select("session_participants", { userId, sessionId: mine.map((p) => p.sessionId) });
      const shared = await tx.select("sessions", { id: theirs.map((p) => p.sessionId), status: ["active", "scheduled"] });
      for (const s of shared) await this.closeSession(tx, s, null, "closed");
      this.notify([`user:${userId}`, `user:${viewer.id}`, ...shared.map((s) => `session:${s.id}`)]);
    });
  }

  async unblock(viewer: Viewer, userId: string) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      await tx.delete("blocks", { blockerId: viewer.id, blockedId: userId });
    });
  }

  async listBlocks(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.active(tx, viewer);
      const rows = await tx.select("blocks", { blockerId: viewer.id });
      const names = await tx.select("profiles", { id: rows.map((r) => r.blockedId) });
      return rows.map((r) => ({ ...r, displayName: names.find((n) => n.id === r.blockedId)?.displayName ?? "Someone" }));
    });
  }

  async report(viewer: Viewer, input: { userId: string; sessionId?: string | null; reason: Report["reason"]; details: string }) {
    const reasons: Report["reason"][] = ["harassment", "inappropriate_media", "spam", "unsafe_advice", "impersonation", "other"];
    if (!reasons.includes(input.reason)) throw new AppError("invalid", "Choose a reason.");
    if (input.userId === viewer.id) throw new AppError("invalid", "You can't report yourself.");
    return this.repo.tx(async (tx) => {
      // Suspended users can still report (e.g. what led to a dispute) — but must exist.
      if (!viewer) throw new AppError("unauthenticated", "Please sign in.");
      const [me] = await tx.select("profiles", { id: viewer.id });
      if (!me) throw new AppError("unauthenticated", "Please sign in.");
      const recent = await tx.count("reports", { reporterId: viewer.id, createdAt: { gt: this.iso(-86_400_000) } });
      await this.rateLimit(tx, recent, LIMITS.reportsPerDay, "reports");
      if (input.sessionId) {
        const { other } = await this.membership(tx, viewer, input.sessionId);
        if (other.userId !== input.userId) throw new AppError("invalid", "That person wasn't in this session.");
      } else {
        const [t] = await tx.select("profiles", { id: input.userId });
        if (!t) throw new AppError("not_found", "Person not found.");
      }
      return tx.insert("reports", {
        id: this.newId(), reporterId: viewer.id, reportedUserId: input.userId, sessionId: input.sessionId ?? null,
        reason: input.reason, details: clean(input.details, 2000), status: "open", createdAt: this.iso(), resolvedAt: null,
      });
    });
  }

  // ───────────────────────── moderation ─────────────────────────

  private async audit(tx: Tx, moderatorId: string, action: ModerationActionKind, f: Partial<ModerationAction>) {
    await tx.insert("moderation_actions", {
      id: this.newId(), moderatorId, action, targetUserId: f.targetUserId ?? null, reportId: f.reportId ?? null,
      credentialId: f.credentialId ?? null, reason: clean(f.reason, 1000), createdAt: this.iso(),
    });
  }

  async modOverview(viewer: Viewer) {
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      const reports = await tx.select("reports", {}, { orderBy: "createdAt", desc: true, limit: 100 });
      const creds = await tx.select("credential_reviews", {}, { orderBy: "createdAt", desc: true, limit: 100 });
      const suspended = await tx.select("profiles", { status: "suspended" });
      const audit = await tx.select("moderation_actions", {}, { orderBy: "createdAt", desc: true, limit: 50 });
      const ids = [...new Set([...reports.flatMap((r) => [r.reporterId, r.reportedUserId]), ...creds.map((c) => c.userId), ...audit.flatMap((a) => [a.moderatorId, a.targetUserId].filter(Boolean) as string[])])];
      const names = new Map((await tx.select("profiles", { id: ids })).map((p) => [p.id, p.displayName]));
      return { reports, credentials: creds, suspended, audit, names: Object.fromEntries(names) };
    });
  }

  /** Opening evidence (session messages) is restricted and always logged. */
  async reportEvidence(viewer: Viewer, reportId: string) {
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      const [report] = await tx.select("reports", { id: reportId });
      if (!report) throw new AppError("not_found", "Report not found.");
      let messages: Message[] = [];
      if (report.sessionId) messages = await tx.select("messages", { sessionId: report.sessionId }, { orderBy: "createdAt", desc: true, limit: 100 });
      await this.audit(tx, viewer.id, "evidence_viewed", { reportId, targetUserId: report.reportedUserId, reason: "Opened report evidence" });
      const names = new Map((await tx.select("profiles", { id: [report.reporterId, report.reportedUserId] })).map((p) => [p.id, p.displayName]));
      const priorReports = await tx.count("reports", { reportedUserId: report.reportedUserId });
      return { report, messages: messages.reverse(), names: Object.fromEntries(names), priorReports };
    });
  }

  async resolveReport(viewer: Viewer, reportId: string, outcome: "actioned" | "dismissed", reason: string) {
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      const [r] = await tx.select("reports", { id: reportId }, { forUpdate: true });
      if (!r) throw new AppError("not_found", "Report not found.");
      if (r.reporterId === viewer.id || r.reportedUserId === viewer.id) throw new AppError("forbidden", "Another moderator needs to handle a report involving you.");
      if (r.status !== "open") throw new AppError("conflict", "This report was already resolved.");
      await tx.update("reports", { id: reportId }, { status: outcome, resolvedAt: this.iso() });
      await this.audit(tx, viewer.id, outcome === "actioned" ? "report_actioned" : "report_dismissed", { reportId, targetUserId: r.reportedUserId, reason });
    });
  }

  async setSuspended(viewer: Viewer, userId: string, suspended: boolean, reason: string) {
    if (!clean(reason, 1000)) throw new AppError("invalid", "A reason is required for the audit log.");
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      if (userId === viewer.id) throw new AppError("forbidden", "You can't change your own account status.");
      const [target] = await tx.select("profiles", { id: userId }, { forUpdate: true });
      if (!target) throw new AppError("not_found", "Person not found.");
      await tx.update("profiles", { id: userId }, { status: suspended ? "suspended" : "active", availableUntil: null });
      if (suspended) {
        const pend = [
          ...(await tx.select("invitations", { helperId: userId, status: "pending" }, { forUpdate: true })),
          ...(await tx.select("invitations", { requesterId: userId, status: "pending" }, { forUpdate: true })),
        ];
        for (const inv of pend) {
          await tx.update("invitations", { id: inv.id }, { status: "unavailable", respondedAt: this.iso() });
          const [req] = await tx.select("requests", { id: inv.requestId }, { forUpdate: true });
          if (req.status === "waiting") await this.setRequestStatus(tx, req, "open");
          this.notify([`user:${inv.requesterId}`, `user:${inv.helperId}`]);
        }
        const parts = await tx.select("session_participants", { userId });
        const live = await tx.select("sessions", { id: parts.map((p) => p.sessionId), status: ["active", "scheduled"] });
        for (const s of live) await this.closeSession(tx, s, null, "closed by the People team");
      }
      await this.audit(tx, viewer.id, suspended ? "suspend" : "unsuspend", { targetUserId: userId, reason });
    });
  }

  async reviewCredential(viewer: Viewer, credentialId: string, status: "verified" | "rejected" | "revoked", note: string) {
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      const [c] = await tx.select("credential_reviews", { id: credentialId }, { forUpdate: true });
      if (!c) throw new AppError("not_found", "Not found.");
      if (c.userId === viewer.id) throw new AppError("forbidden", "Another moderator must review your own credential.");
      const allowed: Record<CredentialReview["status"], string[]> = { pending: ["verified", "rejected"], verified: ["revoked"], rejected: [], revoked: [] };
      if (!allowed[c.status].includes(status)) throw new AppError("conflict", `Can't change a ${c.status} credential to ${status}.`);
      await tx.update("credential_reviews", { id: credentialId }, { status, reviewedBy: viewer.id, reviewedAt: this.iso(), reviewerNote: clean(note, 600) });
      await this.audit(tx, viewer.id, `credential_${status}` as ModerationActionKind, { credentialId, targetUserId: c.userId, reason: note });
    });
  }

  async searchPeople(viewer: Viewer, q: string) {
    return this.repo.tx(async (tx) => {
      await this.moderator(tx, viewer);
      const all = await tx.select("profiles", {}, { orderBy: "displayName", limit: 500 });
      const needle = q.trim().toLowerCase();
      return all.filter((p) => !needle || p.displayName.toLowerCase().includes(needle)).slice(0, 30);
    });
  }

  // ───────────────────────── discovery ─────────────────────────

  /** "Surprise me": an Explore topic drawn only from the viewer's own interests. */
  async surprise(viewer: Viewer, rand: () => number = Math.random) {
    return this.repo.tx(async (tx) => {
      const me = await this.active(tx, viewer);
      const interests = me.interests.filter((t) => getTopic(t) && !isHighStakes(t));
      if (interests.length === 0) return { kind: "no_interests" as const };
      const shuffled = [...interests].sort(() => rand() - 0.5);
      for (const topicId of shuffled) {
        const probe: HelpRequest = {
          id: "probe", requesterId: me.id, question: "", intent: "explore", topicId, tags: [], language: me.languages[0],
          formats: me.formats, timing: "now", preferredTime: null, experienceLevel: "", context: "",
          clarificationQuestion: "", clarificationAnswer: "", broadened: ["topic"], status: "open", autoMatch: false,
          followUpOf: null, createdAt: this.iso(),
        };
        const { eligibleCount } = rankMatches(await this.candidates(tx, probe), {
          request: probe, now: this.now(), blockedIds: await this.blockedIds(tx, me.id), alreadyInvited: new Set(),
        });
        if (eligibleCount > 0) return { kind: "topic" as const, topicId, availableNow: eligibleCount };
      }
      return { kind: "none_available" as const, topicId: shuffled[0] };
    });
  }
}

function sharedDepth(a: string, b: string) {
  const la = topicLineage(a), lb = topicLineage(b);
  let n = 0;
  while (n < la.length && n < lb.length && la[n] === lb[n]) n++;
  return n;
}

export type SessionSnapshot = Awaited<ReturnType<Service["getSession"]>>;
export type InboxData = Awaited<ReturnType<Service["inbox"]>>;
export type { Block, ChecklistItem, Feedback, Takeaway };

// Behavioural tests for the service. Run against the in-memory repo
// (tests/unit) and, when DATABASE_URL_TEST is set, real Postgres (tests/db).

import { describe, expect, it, beforeEach } from "vitest";
import type { Repo } from "../../src/lib/server/repo";
import { AppError } from "../../src/lib/server/service";
import { DEMO_IDS, makeHarness, type Harness } from "./harness";

const { maya, omar, priya, chris, sam, grace, daniel, lena } = DEMO_IDS;

async function code(p: Promise<unknown>) {
  try {
    await p;
    return "ok";
  } catch (e) {
    if (e instanceof AppError) return e.code;
    throw e;
  }
}

const arabicRequest = {
  question: "I understand Arabic, but I'm nervous speaking it.",
  intent: "learn" as const,
  topicId: "languages.arabic.jordanian",
  language: "ar",
  formats: ["voice" as const, "text" as const],
  timing: "now" as const,
  experienceLevel: "new" as const,
};

export function serviceSuite(name: string, makeRepo: () => Promise<Repo>) {
  describe(`${name}: matching eligibility`, () => {
    let h: Harness;
    beforeEach(async () => { h = await makeHarness(await makeRepo()); });

    it("matches an Arabic speaker with Jordanian experience and explains why", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const res = await h.svc.findMatches(h.as(maya), req.id);
      expect(res.matches.map((m) => m.helperId)).toEqual([omar]);
      const reasons = res.matches[0].reasons.join(" | ");
      expect(reasons).toMatch(/Jordanian Arabic/);
      expect(reasons).toMatch(/Welcomes beginners/);
      expect(reasons).toMatch(/Available now for voice/);
    });

    it("never matches the requester to themselves, unavailable, suspended or blocked people", async () => {
      const req = await h.svc.createRequest(h.as(maya), {
        question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice",
        language: "en", formats: ["text"], timing: "now",
      });
      let ids = (await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId);
      expect(ids).toContain(chris);
      expect(ids).toContain(priya);
      expect(ids).not.toContain(maya);

      await h.svc.setAvailableNow(h.as(chris), 0);
      ids = (await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId);
      expect(ids).not.toContain(chris);

      await h.svc.setSuspended(h.as(sam), priya, true, "test");
      ids = (await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId);
      expect(ids).not.toContain(priya);

      await h.svc.block(h.as(omar), maya); // Omar blocks Maya → he never appears for her
      ids = (await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId);
      expect(ids).not.toContain(omar);
    });

    it("excludes incompatible language and format", async () => {
      const req = await h.svc.createRequest(h.as(maya), { ...arabicRequest, formats: ["video"] });
      const res = await h.svc.findMatches(h.as(maya), req.id);
      expect(res.matches).toHaveLength(0); // Omar does text/voice only
      expect(res.broaden.map((b) => b.key)).toContain("formats");
      await h.svc.broaden(h.as(maya), req.id, "formats");
      expect((await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId)).toEqual([omar]);
    });

    it("does not rank new helpers below others just for lacking reviews", async () => {
      const req = await h.svc.createRequest(h.as(maya), {
        question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice",
        language: "en", formats: ["text"], timing: "now", experienceLevel: "new",
      });
      const res = await h.svc.findMatches(h.as(maya), req.id);
      const c = res.matches.find((m) => m.helperId === chris)!;
      expect(c.reasons.join()).toMatch(/New here/);
      expect(c.score).toBeGreaterThanOrEqual(Math.max(...res.matches.map((m) => m.score)) - 5);
    });

    it("refuses high-stakes and emergency requests instead of routing them to helpers", async () => {
      expect(await code(h.svc.createRequest(h.as(maya), { ...arabicRequest, question: "What medication dosage should I take?", topicId: "professional.medical", language: "en" }))).toBe("safety");
      expect(await code(h.svc.createRequest(h.as(maya), { ...arabicRequest, question: "I want to end my life", topicId: "motivation.study", language: "en" }))).toBe("safety");
    });

    it("only shows a verified badge for the reviewed topic, and users cannot verify themselves", async () => {
      const req = await h.svc.createRequest(h.as(maya), {
        question: "What does a financial analyst actually do?", intent: "explore", topicId: "careers.finance.analysis",
        language: "en", formats: ["text"], timing: "now",
      });
      const m = (await h.svc.findMatches(h.as(maya), req.id)).matches.find((x) => x.helperId === priya)!;
      expect(m.verified).toBe(true);
      const rice = await h.svc.createRequest(h.as(maya), {
        question: "How do I make biryani?", intent: "learn", topicId: "cooking.rice.biryani", language: "en", formats: ["text"], timing: "now",
      });
      const m2 = (await h.svc.findMatches(h.as(maya), rice.id)).matches.find((x) => x.helperId === priya)!;
      expect(m2.verified).toBe(false);

      const cred = await h.svc.submitCredential(h.as(chris), { topicId: "cooking.rice", title: "Chef", issuer: "Me", evidenceNote: "" });
      expect(cred.status).toBe("pending");
      expect(await code(h.svc.reviewCredential(h.as(chris), cred.id, "verified", ""))).toBe("forbidden");
    });

    it("rate-limits request creation", async () => {
      for (let i = 0; i < 8; i++) await h.svc.createRequest(h.as(maya), arabicRequest);
      expect(await code(h.svc.createRequest(h.as(maya), arabicRequest))).toBe("rate_limited");
    });
  });

  describe(`${name}: invitations, acceptance races and expiry`, () => {
    let h: Harness;
    beforeEach(async () => { h = await makeHarness(await makeRepo()); });

    it("creates a session only after the helper accepts", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      expect((await h.svc.getRequest(h.as(maya), req.id)).request.status).toBe("waiting");
      expect((await h.svc.getRequest(h.as(maya), req.id)).session).toBeNull();
      const res = await h.svc.respondInvitation(h.as(omar), inv.id, true);
      expect(res.status).toBe("accepted");
      const view = await h.svc.getRequest(h.as(maya), req.id);
      expect(view.request.status).toBe("matched");
      expect(view.session?.status).toBe("active");
    });

    it("allows exactly one winner when accept is clicked twice concurrently", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      const results = await Promise.allSettled([
        h.svc.respondInvitation(h.as(omar), inv.id, true),
        h.svc.respondInvitation(h.as(omar), inv.id, true),
        h.svc.respondInvitation(h.as(omar), inv.id, true),
      ]);
      expect(results.filter((r) => r.status === "fulfilled")).toHaveLength(1);
      const sessions = await h.repo.tx((tx) => tx.select("sessions", { requestId: req.id }));
      expect(sessions).toHaveLength(1);
    });

    it("prevents a helper from being double-booked by two simultaneous requests", async () => {
      const r1 = await h.svc.createRequest(h.as(maya), { ...arabicRequest });
      const r2 = await h.svc.createRequest(h.as(chris), { ...arabicRequest, question: "Can we practise Arabic greetings?" });
      const i1 = await h.svc.inviteHelper(h.as(maya), r1.id, omar);
      const i2 = await h.svc.inviteHelper(h.as(chris), r2.id, omar);
      const results = await Promise.allSettled([
        h.svc.respondInvitation(h.as(omar), i1.id, true),
        h.svc.respondInvitation(h.as(omar), i2.id, true),
      ]);
      expect(results.filter((r) => r.status === "fulfilled")).toHaveLength(1);
      const rejected = results.find((r) => r.status === "rejected") as PromiseRejectedResult;
      expect((rejected.reason as AppError).code).toBe("conflict");
    });

    it("races accept against the requester cancelling: never both", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      const [a, c] = await Promise.allSettled([
        h.svc.respondInvitation(h.as(omar), inv.id, true),
        h.svc.cancelRequest(h.as(maya), req.id),
      ]);
      const view = await h.repo.tx(async (tx) => ({
        req: (await tx.select("requests", { id: req.id }))[0],
        sessions: await tx.select("sessions", { requestId: req.id }),
      }));
      if (a.status === "fulfilled" && (a.value as { status: string }).status === "accepted") {
        expect(c.status).toBe("rejected");
        expect(view.sessions).toHaveLength(1);
      } else {
        expect(view.req.status).toBe("cancelled");
        expect(view.sessions).toHaveLength(0);
      }
    });

    it("only one pending invitation per request", async () => {
      const req = await h.svc.createRequest(h.as(maya), {
        question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice", language: "en", formats: ["text"], timing: "now",
      });
      await h.svc.inviteHelper(h.as(maya), req.id, chris);
      expect(await code(h.svc.inviteHelper(h.as(maya), req.id, priya))).toBe("conflict");
    });

    it("expires unanswered invitations and reopens the request", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      h.clock.advance(4 * 60_000);
      const view = await h.svc.getRequest(h.as(maya), req.id);
      expect(view.request.status).toBe("open");
      expect(view.invitations[0].status).toBe("expired");
      expect(await code(h.svc.respondInvitation(h.as(omar), inv.id, true))).toBe("expired");
      // The expired helper is not re-offered for the same request.
      expect((await h.svc.findMatches(h.as(maya), req.id)).matches.map((m) => m.helperId)).not.toContain(omar);
    });

    it("an accept arriving after the deadline is treated as expired", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      h.clock.advance(3 * 60_000 + 1);
      const res = await h.svc.respondInvitation(h.as(omar), inv.id, true).catch((e) => e);
      expect(res instanceof AppError ? res.code : res.status).toBe("expired");
      expect((await h.repo.tx((tx) => tx.select("sessions", { requestId: req.id })))).toHaveLength(0);
    });

    it("auto-match moves on to the next eligible helper after a decline", async () => {
      const req = await h.svc.createRequest(h.as(maya), {
        question: "Why does my rice keep coming out mushy?", intent: "ask", topicId: "cooking.rice", language: "en", formats: ["text"], timing: "now", autoMatch: true,
      });
      const first = (await h.svc.getRequest(h.as(maya), req.id)).invitations[0];
      expect(first.status).toBe("pending");
      await h.svc.respondInvitation(h.as(first.helperId), first.id, false);
      const after = await h.svc.getRequest(h.as(maya), req.id);
      expect(after.invitations).toHaveLength(2);
      expect(after.invitations[1].helperId).not.toBe(first.helperId);
      expect(after.request.status).toBe("waiting");
    });

    it("cannot accept an invitation addressed to someone else", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      expect(await code(h.svc.respondInvitation(h.as(chris), inv.id, true))).toBe("not_found");
    });

    it("cannot invite someone who isn't eligible by guessing their id", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      expect(await code(h.svc.inviteHelper(h.as(maya), req.id, daniel))).toBe("unavailable");
      expect(await code(h.svc.inviteHelper(h.as(chris), req.id, omar))).toBe("not_found");
    });
  });

  describe(`${name}: privacy, blocking and calls`, () => {
    let h: Harness;
    let sessionId: string;
    beforeEach(async () => {
      h = await makeHarness(await makeRepo());
      const req = await h.svc.createRequest(h.as(maya), { ...arabicRequest });
      const inv = await h.svc.inviteHelper(h.as(maya), req.id, omar);
      sessionId = ((await h.svc.respondInvitation(h.as(omar), inv.id, true)) as { sessionId: string }).sessionId;
    });

    it("only participants can read or write a session", async () => {
      await h.svc.sendMessage(h.as(maya), sessionId, "Marhaba!");
      const snap = await h.svc.getSession(h.as(omar), sessionId);
      expect(snap.messages.map((m) => m.body)).toContain("Marhaba!");
      for (const outsider of [chris, priya, sam]) {
        expect(await code(h.svc.getSession(h.as(outsider), sessionId))).toBe("not_found");
        expect(await code(h.svc.sendMessage(h.as(outsider), sessionId, "hi"))).toBe("not_found");
        expect(await code(h.svc.updateSharedNote(h.as(outsider), sessionId, "x"))).toBe("not_found");
      }
      expect(await code(h.svc.getRequest(h.as(chris), snap.request.id))).toBe("not_found");
    });

    it("keeps private notes private and shared notes shared", async () => {
      await h.svc.updatePrivateNote(h.as(maya), sessionId, "only for me");
      await h.svc.updateSharedNote(h.as(maya), sessionId, "for both");
      const omarView = await h.svc.getSession(h.as(omar), sessionId);
      expect(omarView.privateNote).toBe("");
      expect(omarView.sharedNote.body).toBe("for both");
      expect((await h.svc.getSession(h.as(maya), sessionId)).privateNote).toBe("only for me");
    });

    it("issues call tokens only to participants, and camera only after mutual opt-in", async () => {
      expect(await code(h.svc.callToken(h.as(chris), sessionId))).toBe("not_found");
      const t = await h.svc.callToken(h.as(maya), sessionId);
      expect(t.canPublishVideo).toBe(false); // voice session, no video consent
      expect(h.minted[0].identity).toBe(maya);
      expect(h.minted[0].room).toMatch(/^people-/);
    });

    it("video needs both people to opt in", async () => {
      // Switch the session format to video to test consent gating.
      await h.repo.tx((tx) => tx.update("sessions", { id: sessionId }, { format: "video" }));
      await h.svc.setParticipantFlag(h.as(maya), sessionId, "videoOptIn", true);
      expect((await h.svc.callToken(h.as(maya), sessionId)).canPublishVideo).toBe(false);
      await h.svc.setParticipantFlag(h.as(omar), sessionId, "videoOptIn", true);
      expect((await h.svc.callToken(h.as(maya), sessionId)).canPublishVideo).toBe(true);
    });

    it("blocking ends the session immediately and stops messages and call tokens", async () => {
      await h.svc.block(h.as(maya), omar);
      const snap = await h.svc.getSession(h.as(maya), sessionId);
      expect(snap.session.status).toBe("ended");
      expect(await code(h.svc.sendMessage(h.as(omar), sessionId, "hello?"))).not.toBe("ok");
      expect(await code(h.svc.callToken(h.as(omar), sessionId))).not.toBe("ok");
      expect(await code(h.svc.getProfile(h.as(omar), maya))).toBe("not_found");
    });

    it("refuses call tokens when LiveKit is not configured", async () => {
      const h2 = await makeHarness(await makeRepo(), { withLiveKit: false });
      expect(await code(h2.svc.callToken(h2.as(maya), "00000000-0000-4000-d000-000000000001"))).toBe("not_configured");
    });

    it("refuses call tokens for ended sessions", async () => {
      await h.svc.endSession(h.as(omar), sessionId);
      expect(await code(h.svc.callToken(h.as(maya), sessionId))).toBe("conflict");
    });

    it("wrap-up: feedback once, reconnect only when both opt in", async () => {
      expect(await code(h.svc.wrapUp(h.as(maya), sessionId, { addressed: "yes", reconnect: true }))).toBe("conflict");
      await h.svc.endSession(h.as(maya), sessionId);
      await h.svc.wrapUp(h.as(maya), sessionId, { addressed: "yes", reconnect: true, helpful: 5 });
      expect(await code(h.svc.wrapUp(h.as(maya), sessionId, { addressed: "yes", reconnect: true, helpful: 4 }))).toBe("conflict");
      expect(await code(h.svc.requestFollowUp(h.as(maya), sessionId, { question: "Can we practise again?", timing: "now" }))).toBe("forbidden");
      await h.svc.wrapUp(h.as(omar), sessionId, { addressed: "", reconnect: true });
      const fu = await h.svc.requestFollowUp(h.as(maya), sessionId, { question: "Can we practise again?", timing: "now" });
      expect(fu.invitation.helperId).toBe(omar);
    });
  });

  describe(`${name}: moderation`, () => {
    let h: Harness;
    beforeEach(async () => { h = await makeHarness(await makeRepo()); });

    it("members cannot use moderator tools", async () => {
      const me = h.as(maya);
      expect(await code(h.svc.modOverview(me))).toBe("forbidden");
      expect(await code(h.svc.setSuspended(me, chris, true, "x"))).toBe("forbidden");
      // A forged role on the viewer object is ignored: the role is re-read from the database.
      expect(await code(h.svc.modOverview({ ...me, role: "moderator" }))).toBe("forbidden");
    });

    it("moderators act with an audit trail; evidence views are logged", async () => {
      const { reports } = await h.svc.modOverview(h.as(sam));
      const r = reports[0];
      await h.svc.reportEvidence(h.as(sam), r.id);
      await h.svc.resolveReport(h.as(sam), r.id, "dismissed", "Sample");
      await h.svc.setSuspended(h.as(sam), daniel, true, "Repeated spam");
      const { audit } = await h.svc.modOverview(h.as(sam));
      expect(audit.map((a) => a.action)).toEqual(expect.arrayContaining(["evidence_viewed", "report_dismissed", "suspend"]));
      expect(await code(h.svc.getProfile(h.as(maya), daniel))).toBe("not_found");
      expect(await code(h.svc.createRequest(h.as(daniel), arabicRequest))).toBe("suspended");
    });

    it("moderators cannot change their own status", async () => {
      expect(await code(h.svc.setSuspended(h.as(sam), sam, true, "x"))).toBe("forbidden");
    });

    it("suspending a helper withdraws their pending invitations", async () => {
      const req = await h.svc.createRequest(h.as(maya), arabicRequest);
      await h.svc.inviteHelper(h.as(maya), req.id, omar);
      await h.svc.setSuspended(h.as(sam), omar, true, "test");
      const view = await h.svc.getRequest(h.as(maya), req.id);
      expect(view.invitations[0].status).toBe("unavailable");
      expect(view.request.status).toBe("open");
    });

    it("reports in a session must be about the other participant", async () => {
      expect(await code(h.svc.report(h.as(maya), { userId: grace, sessionId: "00000000-0000-4000-d000-000000000001", reason: "spam", details: "" }))).toBe("invalid");
      expect(await code(h.svc.report(h.as(maya), { userId: priya, sessionId: "00000000-0000-4000-d000-000000000001", reason: "other", details: "test" }))).toBe("ok");
      expect(await code(h.svc.report(h.as(lena), { userId: priya, sessionId: "00000000-0000-4000-d000-000000000001", reason: "other", details: "" }))).toBe("not_found");
    });
  });

  describe(`${name}: async questions`, () => {
    it("lets matching helpers answer questions left for later, and nobody else", async () => {
      const h = await makeHarness(await makeRepo());
      const req = await h.svc.createRequest(h.as(maya), {
        question: "What's the right water ratio for basmati?", intent: "ask", topicId: "cooking.rice", language: "en", formats: ["text"], timing: "now",
      });
      await h.svc.leaveForLater(h.as(maya), req.id);
      const inbox = await h.svc.inbox(h.as(chris));
      expect(inbox.asyncQuestions.map((q) => q.request.id)).toContain(req.id);
      expect(await code(h.svc.respondAsync(h.as(grace), req.id, "1:1.5"))).toBe("not_found"); // bread, not rice
      await h.svc.respondAsync(h.as(chris), req.id, "Rinse well, then about 1:1.5 and rest 10 minutes.");
      const view = await h.svc.getRequest(h.as(maya), req.id);
      expect(view.request.status).toBe("answered");
      expect(view.responses).toHaveLength(1);
    });
  });
}

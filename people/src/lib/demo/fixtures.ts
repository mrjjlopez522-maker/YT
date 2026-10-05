// DEMO FIXTURES — fictional sample people for demo mode only.
// Never loaded when Supabase is configured. Nothing here is a real person,
// a real credential review, or real activity.

import { emptyData } from "../server/memory-repo";
import type { Format, HelperTopic, Profile } from "../domain/types";

export const DEMO_IDS = {
  maya: "00000000-0000-4000-8000-000000000001",
  omar: "00000000-0000-4000-8000-000000000002",
  priya: "00000000-0000-4000-8000-000000000003",
  daniel: "00000000-0000-4000-8000-000000000004",
  grace: "00000000-0000-4000-8000-000000000005",
  yusuf: "00000000-0000-4000-8000-000000000006",
  lena: "00000000-0000-4000-8000-000000000007",
  chris: "00000000-0000-4000-8000-000000000008",
  sam: "00000000-0000-4000-8000-000000000009",
} as const;

/** Personas offered on the demo sign-in screen. */
export const DEMO_PERSONAS = [
  { id: DEMO_IDS.maya, blurb: "Learner with questions about cooking, Arabic and careers" },
  { id: DEMO_IDS.omar, blurb: "Helper: Jordanian Arabic practice, mansaf" },
  { id: DEMO_IDS.priya, blurb: "Helper: financial analysis, biryani" },
  { id: DEMO_IDS.chris, blurb: "New helper: rice dishes, home fixes" },
  { id: DEMO_IDS.sam, blurb: "Moderator: reports, suspensions, credential reviews" },
];

const H = 3600_000;

export function buildDemoData(now = new Date()) {
  const d = emptyData();
  const iso = (ms: number) => new Date(now.getTime() + ms).toISOString();
  const created = iso(-30 * 24 * H);

  const person = (
    id: string, displayName: string, color: string, p: Partial<Profile> & { languages: string[]; formats: Format[] },
  ): Profile => ({
    id, displayName, avatarColor: color, intro: "", canHelpWith: "", curiousAbout: "", timezone: "UTC", locationBroad: "",
    interests: [], cannotAdvise: "", sessionLengthMinutes: 30, availableUntil: null, role: "member", status: "active",
    adultConfirmed: true, onboarded: true, createdAt: created, ...p,
  });

  d.profiles.push(
    person(DEMO_IDS.maya, "Maya", "#4f46e5", {
      intro: "Second-year student. Trying to figure out what comes after college, and learning to cook for myself.",
      canHelpWith: "Study routines, intro statistics", curiousAbout: "Finance careers, Levantine Arabic, cooking rice properly",
      languages: ["en"], formats: ["text", "voice"], timezone: "America/Chicago", locationBroad: "US Midwest",
      interests: ["cooking.rice", "languages.arabic", "careers.finance", "religion.interfaith", "creative.guitar"],
    }),
    person(DEMO_IDS.omar, "Omar", "#0f766e", {
      intro: "Grew up in Amman, now an engineer abroad. Happy to chat in Ammani Arabic at whatever speed you need.",
      canHelpWith: "Everyday Jordanian Arabic, mansaf the way my mother makes it", curiousAbout: "Guitar, baking bread",
      languages: ["ar-JO", "ar", "en"], formats: ["text", "voice"], timezone: "Asia/Amman", locationBroad: "Jordan",
      cannotAdvise: "Formal Arabic grammar exams, immigration paperwork", sessionLengthMinutes: 30,
      availableUntil: iso(8 * H), interests: ["creative.guitar", "cooking.baking"],
    }),
    person(DEMO_IDS.priya, "Priya", "#b45309", {
      intro: "Financial analyst for six years. I like explaining what the job actually involves — the good and the tedious.",
      canHelpWith: "What financial analysts do day to day, breaking into finance, Hyderabadi biryani",
      curiousAbout: "Photography", languages: ["en", "hi"], formats: ["text", "video"], timezone: "America/New_York",
      locationBroad: "US East Coast", cannotAdvise: "Personal investment decisions", sessionLengthMinutes: 45,
      availableUntil: iso(6 * H),
    }),
    person(DEMO_IDS.daniel, "Daniel", "#1d4ed8", {
      intro: "Backend developer. Former procrastinator, current body-double enthusiast.",
      canHelpWith: "Python, getting started on assignments", curiousAbout: "Spanish slang",
      languages: ["en", "es"], formats: ["text", "voice", "video"], timezone: "Europe/Madrid", locationBroad: "Spain",
    }),
    person(DEMO_IDS.grace, "Grace", "#be185d", {
      intro: "Sunday-school volunteer and weekend bread baker.",
      canHelpWith: "What my faith looks like day to day, sourdough troubleshooting", curiousAbout: "Other traditions' holidays",
      languages: ["en"], formats: ["text", "voice"], timezone: "Europe/London", locationBroad: "UK",
      availableUntil: iso(5 * H),
    }),
    person(DEMO_IDS.yusuf, "Yusuf", "#047857", {
      intro: "Recent grad, first in my family to go to college.",
      canHelpWith: "College applications, what Ramadan is like for me", curiousAbout: "Finance careers",
      languages: ["en", "ar"], formats: ["text", "voice"], timezone: "America/Los_Angeles", locationBroad: "US West Coast",
    }),
    person(DEMO_IDS.lena, "Lena", "#7c3aed", {
      intro: "Illustrator. I keep people company while they get started on the hard thing.",
      canHelpWith: "Accountability sessions, sketching basics", curiousAbout: "Cooking",
      languages: ["en", "es-MX"], formats: ["text", "voice", "video"], timezone: "America/Mexico_City", locationBroad: "Mexico",
      availableUntil: iso(4 * H),
    }),
    person(DEMO_IDS.chris, "Chris", "#9a3412", {
      intro: "Line cook turned office worker. New here.",
      canHelpWith: "Rice that isn't mushy, small apartment fixes", curiousAbout: "Learning Arabic",
      languages: ["en"], formats: ["text", "voice"], timezone: "America/Chicago", locationBroad: "US Midwest",
      availableUntil: iso(8 * H), createdAt: iso(-2 * 24 * H),
    }),
    person(DEMO_IDS.sam, "Sam (moderator)", "#334155", {
      intro: "Part of the People pilot team.", languages: ["en"], formats: ["text"], role: "moderator",
      timezone: "UTC",
    }),
  );

  const topic = (helperId: string, topicId: string, kind: HelperTopic["kind"], detail: string, welcomesBeginners = true): HelperTopic =>
    ({ helperId, topicId, kind, detail, welcomesBeginners });
  d.helper_topics.push(
    topic(DEMO_IDS.omar, "languages.arabic.jordanian", "lived", "Native speaker from Amman."),
    topic(DEMO_IDS.omar, "cooking.rice.mansaf", "lived", "Family recipe; cooked it for every Eid."),
    topic(DEMO_IDS.priya, "careers.finance.analysis", "professional", "Six years as an FP&A and equity analyst."),
    topic(DEMO_IDS.priya, "cooking.rice.biryani", "lived", "Hyderabadi dum biryani, learned from my grandmother."),
    topic(DEMO_IDS.daniel, "technology.programming.python", "professional", "Backend developer, mostly Python."),
    topic(DEMO_IDS.daniel, "motivation.study", "lived", "Got through a thesis with body-doubling."),
    topic(DEMO_IDS.grace, "religion.christianity", "lived", "Lifelong churchgoer; I speak only for myself."),
    topic(DEMO_IDS.grace, "cooking.baking", "lived", "Weekend sourdough for eight years."),
    topic(DEMO_IDS.yusuf, "careers.college", "lived", "Went through applications recently as a first-gen student."),
    topic(DEMO_IDS.yusuf, "religion.islam", "lived", "Practising Muslim; happy to share my own experience."),
    topic(DEMO_IDS.lena, "motivation.study", "lived", "I run quiet focus sessions with check-ins."),
    topic(DEMO_IDS.lena, "motivation.projects", "lived", "Freelance deadlines are my life."),
    topic(DEMO_IDS.lena, "creative.drawing", "professional", "Working illustrator."),
    topic(DEMO_IDS.chris, "cooking.rice", "lived", "Cooked a lot of rice on a restaurant line.", true),
    topic(DEMO_IDS.chris, "everyday.home", "lived", "Fixed most things in my own apartment."),
  );

  // Weekly windows (helper's own timezone): Daniel weekday evenings, Yusuf weekends.
  let w = 0;
  const win = (helperId: string, weekday: number, start: number, end: number) =>
    d.availability_windows.push({ id: `00000000-0000-4000-9000-${String(++w).padStart(12, "0")}`, helperId, weekday, startMinute: start * 60, endMinute: end * 60 });
  for (const wd of [1, 2, 3, 4]) win(DEMO_IDS.daniel, wd, 18, 21);
  for (const wd of [0, 6]) win(DEMO_IDS.yusuf, wd, 10, 16);
  for (const wd of [1, 2, 3, 4, 5]) win(DEMO_IDS.omar, wd, 17, 22);
  for (const wd of [1, 3]) win(DEMO_IDS.priya, wd, 19, 21);

  // A platform-reviewed credential (fictional) — applies to one topic only.
  d.credential_reviews.push(
    {
      id: "00000000-0000-4000-a000-000000000001", userId: DEMO_IDS.priya, topicId: "careers.finance.analysis",
      title: "CFA charterholder", issuer: "CFA Institute", evidenceNote: "Public member directory entry.",
      status: "verified", reviewedBy: DEMO_IDS.sam, reviewedAt: iso(-20 * 24 * H), reviewerNote: "Matched directory listing.",
      createdAt: iso(-21 * 24 * H),
    },
    {
      id: "00000000-0000-4000-a000-000000000002", userId: DEMO_IDS.omar, topicId: "languages.arabic.jordanian",
      title: "Certificate in teaching Arabic to non-native speakers", issuer: "University language centre",
      evidenceNote: "Can share the certificate on a call with a moderator.", status: "pending", reviewedBy: null,
      reviewedAt: null, reviewerNote: "", createdAt: iso(-2 * 24 * H),
    },
  );
  d.moderation_actions.push({
    id: "00000000-0000-4000-b000-000000000001", moderatorId: DEMO_IDS.sam, action: "credential_verified",
    targetUserId: DEMO_IDS.priya, reportId: null, credentialId: "00000000-0000-4000-a000-000000000001",
    reason: "Matched directory listing.", createdAt: iso(-20 * 24 * H),
  });

  // One completed sample session so "My learning" and feedback have something to show.
  const reqId = "00000000-0000-4000-c000-000000000001";
  const sesId = "00000000-0000-4000-d000-000000000001";
  d.requests.push({
    id: reqId, requesterId: DEMO_IDS.maya, question: "Is financial analysis mostly Excel? What does a normal week look like?",
    intent: "explore", topicId: "careers.finance.analysis", tags: ["finance", "analyst"], language: "en", formats: ["text"],
    timing: "now", preferredTime: null, experienceLevel: "new", context: "Choosing electives next semester.",
    clarificationQuestion: "", clarificationAnswer: "", broadened: [], status: "closed", autoMatch: false,
    followUpOf: null, createdAt: iso(-6 * 24 * H),
  });
  d.invitations.push({
    id: "00000000-0000-4000-e000-000000000001", requestId: reqId, requesterId: DEMO_IDS.maya, helperId: DEMO_IDS.priya,
    status: "accepted", auto: false, proposedTime: null, expiresAt: iso(-6 * 24 * H + 180_000),
    respondedAt: iso(-6 * 24 * H + 60_000), createdAt: iso(-6 * 24 * H),
  });
  d.sessions.push({
    id: sesId, requestId: reqId, status: "ended", goal: "Understand what a financial analyst does in a normal week.",
    format: "text", scheduledAt: null, startedAt: iso(-6 * 24 * H + 60_000), endedAt: iso(-6 * 24 * H + 40 * 60_000),
    roomName: "people-demo-ended", createdAt: iso(-6 * 24 * H + 60_000), timerEndsAt: null, timerLabel: "",
  });
  d.session_participants.push(
    { sessionId: sesId, userId: DEMO_IDS.maya, role: "requester", videoOptIn: false, keepGoing: false, reconnectOptIn: true, addressed: "yes", leftAt: iso(-6 * 24 * H + 40 * 60_000) },
    { sessionId: sesId, userId: DEMO_IDS.priya, role: "helper", videoOptIn: false, keepGoing: false, reconnectOptIn: true, addressed: "", leftAt: iso(-6 * 24 * H + 40 * 60_000) },
  );
  const msgs: [string | null, string][] = [
    [null, "You're connected. Say hello and agree on what would make this useful."],
    [DEMO_IDS.maya, "Hi! Is it really all spreadsheets?"],
    [DEMO_IDS.priya, "A lot of Excel, yes — but the real job is explaining what the numbers mean to people who decide things."],
    [DEMO_IDS.maya, "What should I take next semester if I'm curious?"],
    [DEMO_IDS.priya, "Accounting basics and one stats course. And try building a tiny model of a company you like."],
  ];
  msgs.forEach(([senderId, body], i) =>
    d.messages.push({ id: `00000000-0000-4000-f000-${String(i + 1).padStart(12, "0")}`, sessionId: sesId, senderId, body, createdAt: iso(-6 * 24 * H + (2 + i) * 60_000) }),
  );
  d.shared_notes.push({
    sessionId: sesId, updatedBy: DEMO_IDS.priya, updatedAt: iso(-6 * 24 * H + 39 * 60_000),
    body: "- Analysts translate numbers into decisions\n- Take accounting basics + one stats course\n- Build a mini model of a company you like",
  });
  d.checklist_items.push(
    { id: "00000000-0000-4000-9100-000000000001", sessionId: sesId, text: "Pick one public company", done: true, createdBy: DEMO_IDS.maya, createdAt: iso(-6 * 24 * H + 30 * 60_000), kind: "task" },
    { id: "00000000-0000-4000-9100-000000000002", sessionId: sesId, text: "Sketch a 3-year revenue model", done: false, createdBy: DEMO_IDS.priya, createdAt: iso(-6 * 24 * H + 31 * 60_000), kind: "task" },
  );
  d.feedback.push({
    id: "00000000-0000-4000-9200-000000000001", sessionId: sesId, fromUser: DEMO_IDS.maya, toUser: DEMO_IDS.priya,
    helpful: 5, respectful: true, comment: "Clear and honest about the boring parts.", createdAt: iso(-6 * 24 * H + 41 * 60_000),
  });
  d.takeaways.push({
    id: "00000000-0000-4000-9300-000000000001", userId: DEMO_IDS.maya, sessionId: sesId, title: "What financial analysts actually do",
    body: "Analysts translate numbers into decisions. Excel is the tool, explaining is the job.",
    nextSteps: "Take accounting basics + one stats course. Build a mini model of a company I like.",
    createdAt: iso(-6 * 24 * H + 42 * 60_000),
  });

  // A sample open report so the moderator queue isn't empty.
  d.reports.push({
    id: "00000000-0000-4000-9400-000000000001", reporterId: DEMO_IDS.grace, reportedUserId: DEMO_IDS.daniel, sessionId: null,
    reason: "spam", details: "(Sample report for the demo moderator queue.) Sent the same link to several people.",
    status: "open", createdAt: iso(-1 * 24 * H), resolvedAt: null,
  });

  return d;
}

// Column map for every table the server touches. The Postgres repo uses it to
// build parameterised SQL (table/column names never come from user input), and
// tests check it against the real migration via information_schema.

import type {
  AsyncResponse, AvailabilityWindow, Block, ChecklistItem, CredentialReview, Feedback, HelpRequest,
  HelperTopic, Invitation, Message, ModerationAction, Participant, PrivateNote, Profile, Report,
  Session, SharedNote, Takeaway,
} from "../domain/types";

type ColKind = "text" | "int" | "bool" | "ts" | "text[]" | "uuid";

export interface SessionRow extends Session {
  timerEndsAt: string | null;
  timerLabel: string;
}
export interface ChecklistRow extends ChecklistItem {
  kind: "step" | "try" | "task";
}

export interface Tables {
  profiles: Profile;
  helper_topics: HelperTopic;
  availability_windows: AvailabilityWindow;
  requests: HelpRequest;
  invitations: Invitation;
  sessions: SessionRow;
  session_participants: Participant;
  messages: Message;
  checklist_items: ChecklistRow;
  shared_notes: SharedNote;
  private_notes: PrivateNote;
  takeaways: Takeaway;
  feedback: Feedback;
  blocks: Block;
  reports: Report;
  credential_reviews: CredentialReview;
  moderation_actions: ModerationAction;
  async_responses: AsyncResponse;
}
export type TableName = keyof Tables;

type Schema = { [T in TableName]: { [K in keyof Tables[T]]-?: ColKind } };

export const SCHEMA: Schema = {
  profiles: {
    id: "uuid", displayName: "text", avatarColor: "text", intro: "text", canHelpWith: "text", curiousAbout: "text",
    languages: "text[]", formats: "text[]", timezone: "text", locationBroad: "text", interests: "text[]",
    cannotAdvise: "text", sessionLengthMinutes: "int", availableUntil: "ts", role: "text", status: "text",
    adultConfirmed: "bool", onboarded: "bool", createdAt: "ts",
  },
  helper_topics: { helperId: "uuid", topicId: "text", kind: "text", detail: "text", welcomesBeginners: "bool" },
  availability_windows: { id: "uuid", helperId: "uuid", weekday: "int", startMinute: "int", endMinute: "int" },
  requests: {
    id: "uuid", requesterId: "uuid", question: "text", intent: "text", topicId: "text", tags: "text[]", language: "text",
    formats: "text[]", timing: "text", preferredTime: "ts", experienceLevel: "text", context: "text",
    clarificationQuestion: "text", clarificationAnswer: "text", broadened: "text[]", status: "text", autoMatch: "bool",
    followUpOf: "uuid", createdAt: "ts",
  },
  invitations: {
    id: "uuid", requestId: "uuid", requesterId: "uuid", helperId: "uuid", status: "text", auto: "bool",
    proposedTime: "ts", expiresAt: "ts", respondedAt: "ts", createdAt: "ts",
  },
  sessions: {
    id: "uuid", requestId: "uuid", status: "text", goal: "text", format: "text", scheduledAt: "ts", startedAt: "ts",
    endedAt: "ts", roomName: "text", createdAt: "ts", timerEndsAt: "ts", timerLabel: "text",
  },
  session_participants: {
    sessionId: "uuid", userId: "uuid", role: "text", videoOptIn: "bool", keepGoing: "bool", reconnectOptIn: "bool",
    addressed: "text", leftAt: "ts",
  },
  messages: { id: "uuid", sessionId: "uuid", senderId: "uuid", body: "text", createdAt: "ts" },
  checklist_items: { id: "uuid", sessionId: "uuid", text: "text", done: "bool", createdBy: "uuid", createdAt: "ts", kind: "text" },
  shared_notes: { sessionId: "uuid", body: "text", updatedBy: "uuid", updatedAt: "ts" },
  private_notes: { sessionId: "uuid", userId: "uuid", body: "text", updatedAt: "ts" },
  takeaways: { id: "uuid", userId: "uuid", sessionId: "uuid", title: "text", body: "text", nextSteps: "text", createdAt: "ts" },
  feedback: {
    id: "uuid", sessionId: "uuid", fromUser: "uuid", toUser: "uuid", helpful: "int", respectful: "bool", comment: "text",
    createdAt: "ts",
  },
  blocks: { blockerId: "uuid", blockedId: "uuid", createdAt: "ts" },
  reports: {
    id: "uuid", reporterId: "uuid", reportedUserId: "uuid", sessionId: "uuid", reason: "text", details: "text",
    status: "text", createdAt: "ts", resolvedAt: "ts",
  },
  credential_reviews: {
    id: "uuid", userId: "uuid", topicId: "text", title: "text", issuer: "text", evidenceNote: "text", status: "text",
    reviewedBy: "uuid", reviewedAt: "ts", reviewerNote: "text", createdAt: "ts",
  },
  moderation_actions: {
    id: "uuid", moderatorId: "uuid", action: "text", targetUserId: "uuid", reportId: "uuid", credentialId: "uuid",
    reason: "text", createdAt: "ts",
  },
  async_responses: { id: "uuid", requestId: "uuid", helperId: "uuid", body: "text", createdAt: "ts" },
};

export const snake = (s: string) => s.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase());

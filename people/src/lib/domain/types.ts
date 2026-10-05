// Core domain types shared by the demo store, the Supabase store and the UI.
// Column names in the SQL migrations mirror these fields in snake_case.

export type Intent = "ask" | "learn" | "move" | "explore";
export type Format = "text" | "voice" | "video";
export type ExperienceKind = "lived" | "professional";
export type Sensitivity = "standard" | "perspective" | "high_stakes";
export type Role = "member" | "moderator";
export type AccountStatus = "active" | "suspended";

export type RequestStatus =
  | "open" // created, nobody invited yet
  | "waiting" // an invitation is pending
  | "matched" // both accepted; a session exists
  | "async_open" // left as a question for a later written response
  | "answered" // an async question received at least one response
  | "closed" // session finished
  | "cancelled";

export type InvitationStatus =
  | "pending"
  | "accepted"
  | "declined"
  | "expired"
  | "cancelled"
  | "unavailable"; // helper became unavailable (blocked, suspended, booked) before answering

export type SessionStatus = "scheduled" | "active" | "ended" | "cancelled";

export type ReportStatus = "open" | "actioned" | "dismissed";
export type CredentialStatus = "pending" | "verified" | "rejected" | "revoked";

export interface Topic {
  id: string; // slug, e.g. "cooking.rice.biryani"
  parentId: string | null;
  name: string;
  description?: string;
  sensitivity: Sensitivity;
  keywords: string[];
}

export interface Profile {
  id: string;
  displayName: string;
  avatarColor: string; // generated initials avatar; no uploads in the MVP
  intro: string;
  canHelpWith: string;
  curiousAbout: string;
  languages: string[]; // BCP-47-ish codes: "en", "ar", "ar-JO", "es"
  formats: Format[];
  timezone: string;
  locationBroad: string;
  interests: string[]; // topic ids for "Surprise me"
  cannotAdvise: string;
  sessionLengthMinutes: number;
  availableUntil: string | null; // ISO; "available now" presence expires on its own
  role: Role;
  status: AccountStatus;
  adultConfirmed: boolean;
  onboarded: boolean;
  createdAt: string;
}

export interface HelperTopic {
  helperId: string;
  topicId: string;
  kind: ExperienceKind;
  detail: string; // self-described experience
  welcomesBeginners: boolean;
}

export interface AvailabilityWindow {
  id: string;
  helperId: string;
  weekday: number; // 0 = Sunday, in the helper's timezone
  startMinute: number;
  endMinute: number;
}

export interface HelpRequest {
  id: string;
  requesterId: string;
  question: string;
  intent: Intent;
  topicId: string;
  tags: string[];
  language: string;
  formats: Format[];
  timing: "now" | "later";
  preferredTime: string | null;
  experienceLevel: "" | "new" | "some" | "experienced";
  context: string;
  clarificationQuestion: string;
  clarificationAnswer: string;
  broadened: string[]; // which preferences the requester agreed to relax
  status: RequestStatus;
  autoMatch: boolean;
  followUpOf: string | null; // session id this request follows up on
  createdAt: string;
}

export interface Invitation {
  id: string;
  requestId: string;
  requesterId: string;
  helperId: string;
  status: InvitationStatus;
  auto: boolean;
  proposedTime: string | null;
  expiresAt: string;
  respondedAt: string | null;
  createdAt: string;
}

export interface Session {
  id: string;
  requestId: string;
  status: SessionStatus;
  goal: string;
  format: Format;
  scheduledAt: string | null;
  startedAt: string | null;
  endedAt: string | null;
  roomName: string; // random; never sufficient on its own to join a call
  createdAt: string;
}

export interface Participant {
  sessionId: string;
  userId: string;
  role: "requester" | "helper";
  videoOptIn: boolean;
  keepGoing: boolean;
  reconnectOptIn: boolean;
  addressed: "" | "yes" | "partly" | "no";
  leftAt: string | null;
}

export interface Message {
  id: string;
  sessionId: string;
  senderId: string | null; // null for system notices
  body: string;
  createdAt: string;
}

export interface ChecklistItem {
  id: string;
  sessionId: string;
  text: string;
  done: boolean;
  createdBy: string;
  createdAt: string;
}

export interface SharedNote {
  sessionId: string;
  body: string;
  updatedBy: string | null;
  updatedAt: string;
}

export interface PrivateNote {
  sessionId: string;
  userId: string;
  body: string;
  updatedAt: string;
}

export interface Takeaway {
  id: string;
  userId: string;
  sessionId: string | null;
  title: string;
  body: string;
  nextSteps: string;
  createdAt: string;
}

export interface Feedback {
  id: string;
  sessionId: string;
  fromUser: string;
  toUser: string;
  helpful: number; // 1..5
  respectful: boolean;
  comment: string; // private: visible to the recipient only as an aggregate + text, never public
  createdAt: string;
}

export interface Block {
  blockerId: string;
  blockedId: string;
  createdAt: string;
}

export interface Report {
  id: string;
  reporterId: string;
  reportedUserId: string;
  sessionId: string | null;
  reason: "harassment" | "inappropriate_media" | "spam" | "unsafe_advice" | "impersonation" | "other";
  details: string;
  status: ReportStatus;
  createdAt: string;
  resolvedAt: string | null;
}

export interface CredentialReview {
  id: string;
  userId: string;
  topicId: string;
  title: string;
  issuer: string;
  evidenceNote: string;
  status: CredentialStatus;
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewerNote: string;
  createdAt: string;
}

export type ModerationActionKind =
  | "suspend"
  | "unsuspend"
  | "report_actioned"
  | "report_dismissed"
  | "credential_verified"
  | "credential_rejected"
  | "credential_revoked"
  | "evidence_viewed"; // a moderator opened restricted report evidence

export interface ModerationAction {
  id: string;
  moderatorId: string;
  action: ModerationActionKind;
  targetUserId: string | null;
  reportId: string | null;
  credentialId: string | null;
  reason: string;
  createdAt: string;
}

export interface AsyncResponse {
  id: string;
  requestId: string;
  helperId: string;
  body: string;
  createdAt: string;
}

/** The signed-in person, as resolved on the server. */
export interface Viewer {
  id: string;
  role: Role;
  status: AccountStatus;
}

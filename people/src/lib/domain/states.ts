// Explicit state machines. The SQL migration enforces the same tables with
// triggers (see supabase/migrations/0002_logic.sql), so both stores agree.

import type { InvitationStatus, RequestStatus, SessionStatus } from "./types";

export const REQUEST_TRANSITIONS: Record<RequestStatus, RequestStatus[]> = {
  open: ["waiting", "async_open", "cancelled"],
  waiting: ["open", "matched", "cancelled"],
  matched: ["closed", "open"], // back to open only if the scheduled session is cancelled
  async_open: ["answered", "waiting", "open", "cancelled"],
  answered: ["closed", "waiting", "open"],
  closed: [],
  cancelled: [],
};

export const INVITATION_TRANSITIONS: Record<InvitationStatus, InvitationStatus[]> = {
  pending: ["accepted", "declined", "expired", "cancelled", "unavailable"],
  accepted: [],
  declined: [],
  expired: [],
  cancelled: [],
  unavailable: [],
};

export const SESSION_TRANSITIONS: Record<SessionStatus, SessionStatus[]> = {
  scheduled: ["active", "cancelled"],
  active: ["ended"],
  ended: [],
  cancelled: [],
};

export class TransitionError extends Error {
  constructor(kind: string, from: string, to: string) {
    super(`Invalid ${kind} transition: ${from} → ${to}`);
    this.name = "TransitionError";
  }
}

function check<S extends string>(table: Record<S, S[]>, kind: string, from: S, to: S) {
  if (!table[from]?.includes(to)) throw new TransitionError(kind, from, to);
}

export const assertRequestTransition = (from: RequestStatus, to: RequestStatus) =>
  check(REQUEST_TRANSITIONS, "request", from, to);
export const assertInvitationTransition = (from: InvitationStatus, to: InvitationStatus) =>
  check(INVITATION_TRANSITIONS, "invitation", from, to);
export const assertSessionTransition = (from: SessionStatus, to: SessionStatus) =>
  check(SESSION_TRANSITIONS, "session", from, to);

/** How long a helper has to answer an invitation. */
export const INVITE_TTL_NOW_MS = 3 * 60 * 1000;
export const INVITE_TTL_LATER_MS = 24 * 60 * 60 * 1000;

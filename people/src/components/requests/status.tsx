import type { RequestStatus, SessionStatus } from "@/lib/domain/types";
import { Badge } from "../ui";

const REQ: Record<RequestStatus, { label: string; tone: "neutral" | "indigo" | "teal" | "amber" | "rose" }> = {
  open: { label: "Open", tone: "indigo" },
  waiting: { label: "Waiting for reply", tone: "amber" },
  matched: { label: "Matched", tone: "teal" },
  async_open: { label: "Left for a written reply", tone: "neutral" },
  answered: { label: "Has replies", tone: "teal" },
  closed: { label: "Done", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};
export function RequestStatusBadge({ status }: { status: RequestStatus }) {
  return <Badge tone={REQ[status].tone}>{REQ[status].label}</Badge>;
}

const SES: Record<SessionStatus, { label: string; tone: "neutral" | "teal" | "amber" }> = {
  scheduled: { label: "Upcoming", tone: "amber" },
  active: { label: "Live", tone: "teal" },
  ended: { label: "Ended", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};
export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  return <Badge tone={SES[status].tone}>{SES[status].label}</Badge>;
}


"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { modEvidence, modResolveReport, modReviewCredential, modSearch, modSetSuspended } from "@/app/actions";
import type { Message } from "@/lib/domain/types";
import { Badge, Button, Input, Notice } from "./ui";

function useRun() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [err, setErr] = useState<string | null>(null);
  const run = (fn: () => Promise<{ ok: boolean; error?: string }>) => start(async () => { setErr(null); const r = await fn(); if (!r.ok) setErr(r.error ?? "Failed"); router.refresh(); });
  return { pending, err, run };
}

export function ReportActions({ reportId, open }: { reportId: string; open: boolean }) {
  const { pending, err, run } = useRun();
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState<null | { messages: Message[]; names: Record<string, string>; priorReports: number }>(null);
  const [loading, startLoad] = useTransition();
  return (
    <div className="mt-3 space-y-3">
      <Button variant="secondary" size="sm" disabled={loading} onClick={() => startLoad(async () => { const r = await modEvidence(reportId); if (r.ok) setEvidence(r.data); })}>
        {evidence ? "Refresh evidence" : "Open evidence (logged)"}
      </Button>
      {evidence && (
        <div className="rounded-xl border border-line bg-paper-2/60 p-3 text-sm">
          <p className="mb-2 text-xs text-muted">Restricted. Your access was recorded in the audit log. {evidence.priorReports} report(s) involve this person in total. Calls are not recorded, so there is no audio or video evidence.</p>
          {evidence.messages.length === 0 ? <p className="text-muted">No session messages attached.</p> : (
            <ol className="max-h-72 space-y-1 overflow-y-auto">
              {evidence.messages.map((m) => (
                <li key={m.id}><span className="font-medium">{m.senderId ? evidence.names[m.senderId] ?? "Participant" : "System"}:</span> {m.body}</li>
              ))}
            </ol>
          )}
        </div>
      )}
      {open && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <label htmlFor={`r-${reportId}`} className="mb-1 block text-xs font-medium text-muted">Reason (saved to audit log)</label>
            <Input id={`r-${reportId}`} value={reason} onChange={(e) => setReason(e.target.value)} className="h-9" />
          </div>
          <Button size="sm" disabled={pending || !reason.trim()} onClick={() => run(() => modResolveReport(reportId, "actioned", reason))}>Mark actioned</Button>
          <Button size="sm" variant="secondary" disabled={pending || !reason.trim()} onClick={() => run(() => modResolveReport(reportId, "dismissed", reason))}>Dismiss</Button>
        </div>
      )}
      {err && <Notice tone="rose">{err}</Notice>}
    </div>
  );
}

export function SuspendControl({ userId, suspended, name }: { userId: string; suspended: boolean; name: string }) {
  const { pending, err, run } = useRun();
  const [reason, setReason] = useState("");
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-40 flex-1">
        <label htmlFor={`s-${userId}`} className="mb-1 block text-xs font-medium text-muted">Reason</label>
        <Input id={`s-${userId}`} value={reason} onChange={(e) => setReason(e.target.value)} className="h-9" />
      </div>
      <Button size="sm" variant={suspended ? "secondary" : "danger"} disabled={pending || !reason.trim()} onClick={() => run(() => modSetSuspended(userId, !suspended, reason))}>
        {suspended ? `Reinstate ${name}` : `Suspend ${name}`}
      </Button>
      {err && <p role="alert" className="w-full text-sm text-rose-ink">{err}</p>}
    </div>
  );
}

export function PeopleSearch() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<{ id: string; displayName: string; status: string; role: string }[] | null>(null);
  const [pending, start] = useTransition();
  return (
    <div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); start(async () => { const r = await modSearch(q); if (r.ok) setRows(r.data); }); }}>
        <label htmlFor="ps" className="sr-only">Search people</label>
        <Input id="ps" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by display name" />
        <Button type="submit" variant="secondary" disabled={pending}>Search</Button>
      </form>
      {rows && (
        <ul className="mt-3 space-y-3">
          {rows.length === 0 && <li className="text-sm text-muted">No one found.</li>}
          {rows.map((p) => (
            <li key={p.id} className="rounded-xl border border-line p-3">
              <p className="mb-2 flex items-center gap-2 text-sm font-medium">{p.displayName} {p.status === "suspended" && <Badge tone="rose">suspended</Badge>} {p.role === "moderator" && <Badge tone="indigo">moderator</Badge>}</p>
              <SuspendControl userId={p.id} suspended={p.status === "suspended"} name={p.displayName} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CredentialActions({ id, status }: { id: string; status: string }) {
  const { pending, err, run } = useRun();
  const [note, setNote] = useState("");
  if (status === "rejected" || status === "revoked") return null;
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2">
      <div className="min-w-40 flex-1">
        <label htmlFor={`c-${id}`} className="mb-1 block text-xs font-medium text-muted">Note to the person</label>
        <Input id={`c-${id}`} value={note} onChange={(e) => setNote(e.target.value)} className="h-9" />
      </div>
      {status === "pending" ? (
        <>
          <Button size="sm" variant="teal" disabled={pending} onClick={() => run(() => modReviewCredential(id, "verified", note))}>Verify for this topic</Button>
          <Button size="sm" variant="secondary" disabled={pending} onClick={() => run(() => modReviewCredential(id, "rejected", note))}>Reject</Button>
        </>
      ) : (
        <Button size="sm" variant="danger" disabled={pending} onClick={() => run(() => modReviewCredential(id, "revoked", note))}>Revoke</Button>
      )}
      {err && <p role="alert" className="w-full text-sm text-rose-ink">{err}</p>}
    </div>
  );
}

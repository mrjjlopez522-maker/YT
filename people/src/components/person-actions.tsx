"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { blockPerson, unblockPerson } from "@/app/actions";
import { ReportDialog } from "./report-dialog";
import { Button } from "./ui";

export function PersonActions({ userId, name }: { userId: string; name: string }) {
  const router = useRouter();
  const [report, setReport] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="ghost" size="sm" onClick={() => setReport(true)}>Report</Button>
      {confirm ? (
        <span className="flex items-center gap-2 text-sm">
          Block {name}?
          <Button size="sm" variant="danger" disabled={pending} onClick={() => start(async () => { await blockPerson(userId); router.push("/"); })}>Block</Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
        </span>
      ) : <Button variant="danger" size="sm" onClick={() => setConfirm(true)}>Block</Button>}
      {report && <ReportDialog userId={userId} name={name} onClose={() => setReport(false)} />}
    </div>
  );
}

export function UnblockButton({ userId }: { userId: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return <Button variant="ghost" size="sm" disabled={pending} onClick={() => start(async () => { await unblockPerson(userId); router.refresh(); })}>Unblock</Button>;
}

"use client";
import { useState, useTransition } from "react";
import { resetDemoData } from "@/app/actions";
import { Button } from "./ui";

export function ResetDemo() {
  const [pending, start] = useTransition();
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-center gap-3">
      <Button variant="secondary" size="sm" disabled={pending} onClick={() => start(async () => { await resetDemoData(); setDone(true); })}>Reset demo data</Button>
      {done && <span role="status" className="text-sm text-muted">Back to the starting sample data.</span>}
    </div>
  );
}

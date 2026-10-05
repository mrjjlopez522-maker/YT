"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { addTakeaway, deleteTakeaway } from "@/app/actions";
import { Button, Card, Input, Label, Textarea } from "./ui";

export function NewTakeaway() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [next, setNext] = useState("");
  const [pending, start] = useTransition();
  if (!open) return <Button variant="secondary" onClick={() => setOpen(true)}>Add a note</Button>;
  return (
    <Card className="w-full p-5">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); start(async () => { const r = await addTakeaway({ title, body, nextSteps: next }); if (r.ok) { setOpen(false); setTitle(""); setBody(""); setNext(""); router.refresh(); } }); }}>
        <div><Label htmlFor="nt">Title</Label><Input id="nt" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} /></div>
        <div><Label htmlFor="nb">Notes</Label><Textarea id="nb" rows={4} value={body} onChange={(e) => setBody(e.target.value)} /></div>
        <div><Label htmlFor="nn">Next steps</Label><Textarea id="nn" rows={2} value={next} onChange={(e) => setNext(e.target.value)} /></div>
        <div className="flex gap-2"><Button type="submit" disabled={pending || !title.trim()}>Save</Button><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button></div>
      </form>
    </Card>
  );
}

export function DeleteTakeaway({ id }: { id: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  return <Button variant="ghost" size="sm" disabled={pending} onClick={() => start(async () => { await deleteTakeaway(id); router.refresh(); })}>Delete</Button>;
}

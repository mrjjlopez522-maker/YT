// In-process change notifications used by demo mode's server-sent events.
// In live mode, browsers subscribe to Supabase Realtime instead (RLS-filtered).
import { EventEmitter } from "node:events";

const g = globalThis as unknown as { __peopleBus?: EventEmitter };
export const bus = g.__peopleBus ?? (g.__peopleBus = new EventEmitter().setMaxListeners(1000));

export function publish(topics: string[]) {
  for (const t of new Set(topics)) bus.emit("change", t);
}

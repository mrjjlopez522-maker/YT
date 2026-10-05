"use client";
import { createContext, useContext } from "react";
import type { PublicConfig } from "@/lib/config";

const Ctx = createContext<PublicConfig>({ mode: "demo", livekit: false, ai: false, supabaseUrl: null, supabaseAnonKey: null });

export function ConfigProvider({ value, children }: { value: PublicConfig; children: React.ReactNode }) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const usePublicConfig = () => useContext(Ctx);

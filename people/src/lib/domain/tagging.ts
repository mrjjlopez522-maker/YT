// Deterministic keyword tagging. Works with no AI provider configured.
// An optional provider (src/lib/ai) can refine suggestions, but the user always
// confirms or corrects the topic before anything is matched.

import { TOPICS, getTopic, isHighStakes, topicLineage } from "./topics";
import type { Intent } from "./types";

export interface TagSuggestion {
  topicId: string;
  score: number;
  matched: string[];
}

export interface Analysis {
  suggestions: TagSuggestion[];
  intent: Intent;
  language: string | null;
  safety: SafetyFlag;
  clarification: string | null;
}

export type SafetyFlag =
  | { kind: "ok" }
  | { kind: "emergency" }
  | { kind: "high_stakes"; topicId: string };

const normalize = (s: string) =>
  ` ${s.toLowerCase().replace(/[’']/g, "'").replace(/[^\p{L}\p{N}' ]+/gu, " ").replace(/\s+/g, " ")} `;

function hasPhrase(text: string, phrase: string) {
  return text.includes(` ${phrase.toLowerCase()} `);
}

/** Crude stemming so "procrastinating" matches "procrastinate" etc. */
function variants(word: string): string[] {
  const out = [word];
  if (!word.includes(" ")) {
    out.push(word + "s", word + "ing", word + "ed");
    if (word.endsWith("e")) out.push(word.slice(0, -1) + "ing");
  }
  return out;
}

function ownMatches(text: string, keywords: string[]) {
  const hit = keywords.filter((k) => variants(k).some((v) => hasPhrase(text, v)));
  // "speak" and "speaking" are one signal, not two.
  return hit.filter((k, i) => !hit.slice(0, i).some((o) => variants(o).some((v) => variants(k).includes(v))));
}

export function suggestTopics(question: string, limit = 3): TagSuggestion[] {
  const text = normalize(question);
  const own = new Map(TOPICS.map((t) => [t.id, ownMatches(text, t.keywords)]));
  const weight = (ks: string[]) => ks.reduce((s, k) => s + (k.includes(" ") ? 2 : 1), 0);
  const scored: TagSuggestion[] = [];
  for (const t of TOPICS) {
    const matched = own.get(t.id)!;
    if (matched.length === 0) continue;
    // Evidence for a parent also supports its children, so a child with its own
    // evidence always outranks its parent (more specific wins).
    const lineage = topicLineage(t.id);
    const inherited = lineage.slice(0, -1).reduce((s, id) => s + weight(own.get(id)!), 0);
    const score = weight(matched) + inherited + lineage.length * 0.25;
    scored.push({ topicId: t.id, score, matched });
  }
  // Propagate: a matching leaf implies its ancestors are relevant, but the leaf is the suggestion.
  scored.sort((a, b) => b.score - a.score);
  const out: TagSuggestion[] = [];
  for (const s of scored) {
    // Skip an ancestor if a descendant was already suggested.
    if (out.some((o) => topicLineage(o.topicId).includes(s.topicId))) continue;
    out.push(s);
    if (out.length >= limit) break;
  }
  return out;
}

const EMERGENCY = [
  "suicide", "kill myself", "end my life", "want to die", "hurt myself", "self harm", "overdose",
  "being abused", "in danger", "someone is hurting me", "heart attack", "can't breathe", "cant breathe", "emergency",
];

export function safetyCheck(question: string, topicId?: string): SafetyFlag {
  const text = normalize(question);
  if (EMERGENCY.some((p) => hasPhrase(text, p))) return { kind: "emergency" };
  if (topicId && isHighStakes(topicId)) return { kind: "high_stakes", topicId };
  const top = suggestTopics(question, 5).find((s) => isHighStakes(s.topicId));
  if (top) return { kind: "high_stakes", topicId: top.topicId };
  return { kind: "ok" };
}

export function guessIntent(question: string): Intent {
  const t = normalize(question);
  if (/(procrastinat|motivat|accountab| start my | stop putting| keep me | get moving| focus )/.test(t)) return "move";
  if (/ (curious|what is it like|perspective|culture|how someone|what does .* actually do)/.test(t)) return "explore";
  if (/ (teach|show me|learn|how to|how do i|practice|practise|nervous speaking)/.test(t)) return "learn";
  return "ask";
}

const LANG_HINTS: [RegExp, string][] = [
  [/\barabic\b|عربي/i, "ar"],
  [/\bspanish\b|español/i, "es"],
];

export function guessLanguage(question: string): string | null {
  for (const [re, code] of LANG_HINTS) if (re.test(question)) return code;
  return null;
}

/** At most one short follow-up, only when it would materially improve matching. */
export function clarificationFor(question: string, topicId: string | null): string | null {
  const words = normalize(question).trim().split(" ").filter(Boolean);
  if (!topicId) return "Which area is this closest to? Picking a topic helps us find the right person.";
  if (topicId.startsWith("languages.") && !/\b(beginner|fluent|basic|intermediate|nervous|understand)\b/i.test(question))
    return "How comfortable are you speaking it today — just starting, or able to hold a basic conversation?";
  if (topicId.startsWith("careers.") && words.length < 12)
    return "Where are you right now — exploring options, applying, or already working in the field?";
  if (topicId.startsWith("cooking.") && /\b(keeps?|always|every time)\b/i.test(question) && !/\b(pot|cooker|stove|ratio|water)\b/i.test(question))
    return "What are you cooking it in, and roughly how much water do you use?";
  return null;
}

export function analyze(question: string): Analysis {
  const suggestions = suggestTopics(question);
  const primary = suggestions.find((s) => !isHighStakes(s.topicId)) ?? suggestions[0];
  return {
    suggestions,
    intent: guessIntent(question),
    language: guessLanguage(question),
    safety: safetyCheck(question),
    clarification: clarificationFor(question, primary?.topicId ?? null),
  };
}

export function describeTopic(id: string) {
  return getTopic(id)?.name ?? id;
}

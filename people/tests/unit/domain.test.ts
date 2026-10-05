import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { analyze, safetyCheck, suggestTopics, guessIntent } from "../../src/lib/domain/tagging";
import { assertRequestTransition, assertInvitationTransition } from "../../src/lib/domain/states";
import { windowCovers } from "../../src/lib/domain/matching";
import { topicsSql } from "../../scripts/gen-topics-sql";

describe("tagging", () => {
  it.each([
    ["I'm considering finance. What does a financial analyst actually do?", "careers.finance.analysis"],
    ["Why does my rice keep coming out mushy?", "cooking.rice"],
    ["I understand Arabic, but I'm nervous speaking it.", "languages.arabic"],
    ["Help me stop procrastinating and start my assignment.", "motivation.study"],
    ["I'm curious about how someone practices their religion.", "religion.interfaith"],
  ])("suggests a topic for %s", (q, topic) => {
    expect(suggestTopics(q)[0]?.topicId).toBe(topic);
  });

  it("guesses intent", () => {
    expect(guessIntent("Help me stop procrastinating and start my assignment.")).toBe("move");
    expect(guessIntent("I'm curious about how someone practices their religion.")).toBe("explore");
    expect(guessIntent("Can you show me how to tune a guitar?")).toBe("learn");
  });

  it("asks at most one clarification", () => {
    const a = analyze("I understand Arabic, but I'm nervous speaking it.");
    expect(typeof a.clarification === "string" || a.clarification === null).toBe(true);
    expect(analyze("Why does my rice keep coming out mushy?").clarification).toMatch(/water/);
  });

  it("flags emergencies and high-stakes questions", () => {
    expect(safetyCheck("I want to kill myself").kind).toBe("emergency");
    expect(safetyCheck("What dosage of this medication should I take?").kind).toBe("high_stakes");
    expect(safetyCheck("How do I fold dumplings?").kind).toBe("ok");
  });
});

describe("state machines", () => {
  it("rejects invalid transitions", () => {
    expect(() => assertRequestTransition("closed", "open")).toThrow();
    expect(() => assertInvitationTransition("accepted", "declined")).toThrow();
    expect(() => assertRequestTransition("waiting", "matched")).not.toThrow();
  });
});

describe("availability windows", () => {
  it("respects the helper's timezone", () => {
    const w = [{ id: "w", helperId: "h", weekday: 1, startMinute: 18 * 60, endMinute: 21 * 60 }];
    // Monday 19:00 in Madrid (CEST, UTC+2) = 17:00Z
    expect(windowCovers(w, "Europe/Madrid", "2026-10-05T17:00:00Z")).toBe(true);
    expect(windowCovers(w, "Europe/Madrid", "2026-10-05T20:00:00Z")).toBe(false);
  });
});

describe("generated SQL", () => {
  it("topics migration is in sync with topics.ts (run npm run gen:topics)", () => {
    const file = readFileSync(path.resolve(__dirname, "../../supabase/migrations/0003_topics.sql"), "utf8");
    expect(file).toBe(topicsSql());
  });
});

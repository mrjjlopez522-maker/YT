// Provider adapter for optional AI-assisted categorisation.
// Without ANTHROPIC_API_KEY, or on any error/refusal, People uses the
// deterministic keyword tagger. Either way the user confirms the topic.
import "server-only";
import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";
import { serverConfig } from "../config";
import { analyze, safetyCheck, type Analysis } from "../domain/tagging";
import { getTopic, isHighStakes, TOPICS } from "../domain/topics";

export interface Categorizer {
  name: string;
  analyze(question: string): Promise<Analysis & { source: "keywords" | "ai" }>;
}

export const keywordCategorizer: Categorizer = {
  name: "keywords",
  async analyze(question) {
    return { ...analyze(question), source: "keywords" };
  },
};

const topicIds = TOPICS.map((t) => t.id) as [string, ...string[]];
const Result = z.object({
  topic_ids: z.array(z.enum(topicIds)).describe("Up to 3 most specific matching topic ids, best first"),
  intent: z.enum(["ask", "learn", "move", "explore"]),
  clarifying_question: z.string().describe("One short follow-up that would improve matching, or empty string"),
});

function anthropicCategorizer(): Categorizer {
  const client = new Anthropic({ timeout: 8000, maxRetries: 1 });
  const catalog = TOPICS.map((t) => `${t.id}: ${t.name}`).join("\n");
  return {
    name: "anthropic",
    async analyze(question) {
      const base = analyze(question);
      try {
        const res = await client.messages.parse({
          model: "claude-opus-5-5",
          max_tokens: 2000,
          output_config: { effort: "low", format: zodOutputFormat(Result) },
          system:
            "You route questions on a peer-help app to topics. Pick from the catalog only. " +
            "Ask a clarifying question only if the answer would change which person is a good match.\n\nCatalog:\n" + catalog,
          messages: [{ role: "user", content: question }],
        });
        const out = res.stop_reason === "refusal" ? null : res.parsed_output;
        if (!out) return { ...base, source: "keywords" };
        const ids = out.topic_ids.filter((id) => getTopic(id)).slice(0, 3);
        if (ids.length === 0) return { ...base, source: "keywords" };
        return {
          suggestions: ids.map((topicId, i) => ({ topicId, score: 3 - i, matched: [] })),
          intent: out.intent,
          language: base.language,
          // Safety screening always uses the deterministic rules too.
          safety: base.safety.kind !== "ok" ? base.safety : safetyCheck(question, ids.find(isHighStakes)),
          clarification: out.clarifying_question.trim().slice(0, 200) || null,
          source: "ai",
        };
      } catch {
        return { ...base, source: "keywords" };
      }
    },
  };
}

export function getCategorizer(): Categorizer {
  return serverConfig().ai.configured ? anthropicCategorizer() : keywordCategorizer;
}

import { rootOf } from "./topics";
import type { Intent } from "./types";

export const INTENTS: { id: Intent; label: string; blurb: string; example: string }[] = [
  { id: "ask", label: "Ask", blurb: "Get help with a specific question.", example: "Why does my rice keep coming out mushy?" },
  { id: "learn", label: "Learn", blurb: "Have someone teach or demonstrate something.", example: "I understand Arabic, but I'm nervous speaking it." },
  { id: "move", label: "Get moving", blurb: "Find encouragement or an accountability partner.", example: "Help me stop procrastinating and start my assignment." },
  { id: "explore", label: "Explore", blurb: "Discover a new perspective, culture, or interest.", example: "I'm curious about how someone practices their religion." },
];

export const intentLabel = (i: Intent) => INTENTS.find((x) => x.id === i)?.label ?? i;

export const EXAMPLE_PROMPTS = [
  "I'm considering finance. What does a financial analyst actually do?",
  "Why does my rice keep coming out mushy?",
  "I understand Arabic, but I'm nervous speaking it.",
  "Help me stop procrastinating and start my assignment.",
  "I'm curious about how someone practices their religion.",
];

const EXPLORE: Record<string, string[]> = {
  religion: [
    "What does an ordinary day of practice look like for you?",
    "What's something people often misunderstand about your tradition?",
    "Is there a holiday or ritual that means a lot to you personally?",
  ],
  languages: [
    "What's a phrase you use every day that textbooks never teach?",
    "What surprised you most when you first moved or travelled there?",
    "What's a polite thing to say that visitors usually get wrong?",
  ],
  cooking: [
    "What dish reminds you of home, and who taught it to you?",
    "What's the one technique that changed how you cook?",
  ],
  careers: [
    "What does a normal Tuesday at work actually look like?",
    "What do you wish you had known before starting?",
  ],
  default: [
    "How did you first get into this?",
    "What's something a beginner usually gets wrong?",
    "What would you tell yourself when you were starting out?",
  ],
};

export function explorePrompts(topicId: string) {
  return EXPLORE[rootOf(topicId)] ?? EXPLORE.default;
}

export const RESPECT_NOTE =
  "Everyone here shares their own perspective, not official teaching for a whole tradition or culture. Ask with curiosity, listen generously, and it's fine to say “I'd rather not get into that.”";

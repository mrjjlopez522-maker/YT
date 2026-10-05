// Extensible taxonomy: category → subtopic → specific topic.
// The same list seeds the database (scripts/gen-seed-sql.ts writes supabase/seed/topics.sql).

import type { Sensitivity, Topic } from "./types";

type Node = {
  id: string;
  name: string;
  keywords?: string[];
  sensitivity?: Sensitivity;
  description?: string;
  children?: Node[];
};

const TREE: Node[] = [
  {
    id: "careers",
    name: "Careers & college",
    description: "What a job is really like, applications, first steps.",
    keywords: ["career", "job", "work", "interview", "resume", "cv", "college", "university", "degree", "major", "internship", "salary"],
    children: [
      {
        id: "careers.finance",
        name: "Finance",
        keywords: ["finance", "bank", "banking", "investment", "accounting", "accountant"],
        children: [
          { id: "careers.finance.analysis", name: "Financial analysis", keywords: ["financial analyst", "analyst", "excel", "modeling", "valuation"] },
        ],
      },
      {
        id: "careers.software",
        name: "Software & data jobs",
        keywords: ["software engineer", "developer job", "data scientist", "tech job", "bootcamp"],
      },
      {
        id: "careers.college",
        name: "College applications",
        keywords: ["application", "admissions", "essay", "scholarship", "transfer", "gpa", "sat"],
      },
      { id: "careers.teaching", name: "Teaching", keywords: ["teacher", "teaching", "classroom"] },
    ],
  },
  {
    id: "cooking",
    name: "Cooking",
    description: "Techniques, fixes and family dishes.",
    keywords: ["cook", "cooking", "recipe", "kitchen", "bake", "baking", "food", "dish", "meal"],
    children: [
      {
        id: "cooking.rice",
        name: "Rice dishes",
        keywords: ["rice", "mushy", "sticky rice", "pilaf", "risotto"],
        children: [
          { id: "cooking.rice.biryani", name: "Biryani", keywords: ["biryani", "dum", "basmati"] },
          { id: "cooking.rice.mansaf", name: "Mansaf", keywords: ["mansaf", "jameed"] },
        ],
      },
      { id: "cooking.baking", name: "Bread & baking", keywords: ["bread", "dough", "sourdough", "yeast", "cake", "oven"] },
      { id: "cooking.everyday", name: "Everyday meals", keywords: ["meal prep", "dinner", "budget meals", "knife", "spices"] },
    ],
  },
  {
    id: "languages",
    name: "Culture & languages",
    description: "Practice speaking, customs, and living somewhere new.",
    keywords: ["language", "speak", "speaking", "practice", "fluent", "accent", "grammar", "culture", "translate"],
    children: [
      {
        id: "languages.arabic",
        name: "Arabic",
        keywords: ["arabic", "عربي", "fusha", "levantine"],
        children: [
          { id: "languages.arabic.jordanian", name: "Jordanian conversational practice", keywords: ["jordanian", "jordan", "amman", "levantine"] },
          { id: "languages.arabic.egyptian", name: "Egyptian conversational practice", keywords: ["egyptian", "masri", "cairo"] },
        ],
      },
      { id: "languages.spanish", name: "Spanish", keywords: ["spanish", "español", "mexican spanish"] },
      { id: "languages.moving", name: "Moving to a new country", keywords: ["moving abroad", "immigrant", "expat", "new country", "customs"] },
    ],
  },
  {
    id: "religion",
    name: "Religion & spirituality",
    description: "Personal perspectives shared respectfully. Not official teaching.",
    sensitivity: "perspective",
    keywords: ["religion", "religious", "faith", "pray", "prayer", "spiritual", "spirituality", "church", "mosque", "temple", "synagogue", "practice their religion"],
    children: [
      { id: "religion.islam", name: "Islam in daily life", sensitivity: "perspective", keywords: ["islam", "muslim", "ramadan", "salah", "quran"] },
      { id: "religion.christianity", name: "Christianity in daily life", sensitivity: "perspective", keywords: ["christian", "christianity", "bible", "church"] },
      { id: "religion.judaism", name: "Judaism in daily life", sensitivity: "perspective", keywords: ["jewish", "judaism", "shabbat", "torah"] },
      { id: "religion.buddhism", name: "Buddhism & meditation", sensitivity: "perspective", keywords: ["buddhism", "buddhist", "meditation", "mindfulness"] },
      { id: "religion.interfaith", name: "Curious about other faiths", sensitivity: "perspective", keywords: ["interfaith", "other religions", "how someone practices"] },
    ],
  },
  {
    id: "motivation",
    name: "Motivation & accountability",
    description: "A nudge, a body double, a check-in.",
    keywords: ["procrastinate", "procrastinating", "motivation", "motivated", "focus", "accountability", "habit", "discipline", "stuck", "start my"],
    children: [
      { id: "motivation.study", name: "Study & assignments", keywords: ["assignment", "homework", "study", "studying", "essay", "exam", "thesis"] },
      { id: "motivation.fitness", name: "Fitness habits", keywords: ["workout", "gym", "running", "exercise"] },
      { id: "motivation.projects", name: "Personal projects", keywords: ["side project", "finish", "deadline", "creative block"] },
    ],
  },
  {
    id: "technology",
    name: "Technology",
    description: "Code, devices, and getting unstuck.",
    keywords: ["computer", "tech", "technology", "code", "coding", "app", "software", "laptop"],
    children: [
      {
        id: "technology.programming",
        name: "Programming",
        keywords: ["programming", "bug", "javascript", "error", "function"],
        children: [
          { id: "technology.programming.python", name: "Python", keywords: ["python", "pandas", "django"] },
          { id: "technology.programming.web", name: "Web development", keywords: ["html", "css", "react", "website"] },
        ],
      },
      { id: "technology.devices", name: "Phones & computers", keywords: ["phone", "iphone", "android", "wifi", "printer", "backup"] },
    ],
  },
  {
    id: "creative",
    name: "Creative skills & hobbies",
    description: "Making things, playing things.",
    keywords: ["hobby", "creative", "art", "draw", "paint", "music", "instrument", "craft"],
    children: [
      { id: "creative.guitar", name: "Guitar", keywords: ["guitar", "chords", "strumming"] },
      { id: "creative.drawing", name: "Drawing & painting", keywords: ["drawing", "sketch", "watercolor", "painting"] },
      { id: "creative.photography", name: "Photography", keywords: ["photo", "photography", "camera", "lens"] },
      { id: "creative.knitting", name: "Knitting & sewing", keywords: ["knit", "knitting", "sew", "sewing", "crochet"] },
    ],
  },
  {
    id: "everyday",
    name: "Everyday practical skills",
    description: "Small problems with real answers.",
    keywords: ["fix", "how do i", "repair", "home", "apartment", "budget"],
    children: [
      { id: "everyday.home", name: "Home fixes", keywords: ["leak", "drain", "paint wall", "shelf", "drill", "toilet"] },
      { id: "everyday.money", name: "Budgeting basics", keywords: ["budget", "budgeting", "saving money", "rent", "bills"] },
      { id: "everyday.cars", name: "Car basics", keywords: ["car", "tire", "oil change", "battery"] },
      { id: "everyday.plants", name: "Plants & gardening", keywords: ["plant", "plants", "garden", "watering", "succulent"] },
    ],
  },
  // High-stakes areas exist so they can be recognised and handled carefully.
  // Professional advice is not available in this MVP.
  {
    id: "professional",
    name: "Medical, legal & financial advice",
    description: "Not available in this pilot. People can share experiences, not professional advice.",
    sensitivity: "high_stakes",
    keywords: [],
    children: [
      { id: "professional.medical", name: "Medical", sensitivity: "high_stakes", keywords: ["diagnose", "symptom", "symptoms", "medication", "dosage", "doctor", "pain", "pregnant", "rash", "prescription"] },
      { id: "professional.legal", name: "Legal", sensitivity: "high_stakes", keywords: ["lawyer", "lawsuit", "sue", "legal advice", "visa denied", "court", "custody", "contract dispute"] },
      { id: "professional.investing", name: "Personal investment advice", sensitivity: "high_stakes", keywords: ["which stock", "should i invest", "crypto advice", "retirement account"] },
    ],
  },
];

function flatten(nodes: Node[], parentId: string | null, inherited: Sensitivity, out: Topic[]) {
  for (const n of nodes) {
    const sensitivity = n.sensitivity ?? inherited;
    out.push({ id: n.id, parentId, name: n.name, description: n.description, sensitivity, keywords: n.keywords ?? [] });
    if (n.children) flatten(n.children, n.id, sensitivity, out);
  }
  return out;
}

export const TOPICS: Topic[] = flatten(TREE, null, "standard", []);
const BY_ID = new Map(TOPICS.map((t) => [t.id, t]));

export const getTopic = (id: string) => BY_ID.get(id);
export const rootTopics = () => TOPICS.filter((t) => t.parentId === null);
export const childTopics = (id: string) => TOPICS.filter((t) => t.parentId === id);

/** ["cooking", "cooking.rice", "cooking.rice.biryani"] */
export function topicLineage(id: string): string[] {
  const out: string[] = [];
  let cur = BY_ID.get(id);
  while (cur) {
    out.unshift(cur.id);
    cur = cur.parentId ? BY_ID.get(cur.parentId) : undefined;
  }
  return out;
}

export function topicPath(id: string): string {
  return topicLineage(id)
    .map((t) => BY_ID.get(t)!.name)
    .join(" → ");
}

export function rootOf(id: string): string {
  return topicLineage(id)[0] ?? id;
}

/** Shared ancestry depth: 3 = same leaf, 0 = unrelated. */
export function topicAffinity(a: string, b: string): number {
  const la = topicLineage(a);
  const lb = topicLineage(b);
  let n = 0;
  while (n < la.length && n < lb.length && la[n] === lb[n]) n++;
  return n;
}

export const isHighStakes = (id: string) => BY_ID.get(id)?.sensitivity === "high_stakes";
export const isPerspective = (id: string) => BY_ID.get(id)?.sensitivity === "perspective";

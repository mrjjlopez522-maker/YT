"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { ArrowLeft, Sparkles } from "lucide-react";
import { analyzeQuestion, createRequest } from "@/app/actions";
import { LANGUAGES } from "@/lib/domain/languages";
import { explorePrompts, INTENTS } from "@/lib/domain/prompts";
import { safetyCheck, type Analysis } from "@/lib/domain/tagging";
import { getTopic, isHighStakes, isPerspective, topicPath } from "@/lib/domain/topics";
import type { Format, Intent } from "@/lib/domain/types";
import { TopicPicker } from "../topic-picker";
import { Button, Card, Chip, Input, Label, Notice, PageHeader, Select, Spinner, Textarea } from "../ui";
import { RESPECT_NOTE } from "@/lib/domain/prompts";

const FORMATS: { id: Format; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "voice", label: "Voice" },
  { id: "video", label: "Video" },
];

export function RequestWizard(props: {
  initialQuestion: string; initialIntent: Intent | ""; initialTopic: string; surprise: boolean; noneAvailable: boolean;
  languages: string[]; formats: Format[];
}) {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(props.initialQuestion.length >= 5 ? 2 : 1);
  const [question, setQuestion] = useState(props.initialQuestion || (props.surprise && props.initialTopic ? explorePrompts(props.initialTopic)[0] : ""));
  const [analysis, setAnalysis] = useState<(Analysis & { source: string }) | null>(null);
  const [analyzing, startAnalyze] = useTransition();
  const [submitting, startSubmit] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const [topicId, setTopicId] = useState(props.initialTopic);
  const [intent, setIntent] = useState<Intent>(props.initialIntent || "ask");
  const [language, setLanguage] = useState(props.languages[0] ?? "en");
  const [formats, setFormats] = useState<Format[]>(props.formats.length ? props.formats.filter((f) => f !== "video").slice(0, 2) : ["text"]);
  const [timing, setTiming] = useState<"now" | "later">("now");
  const [preferredTime, setPreferredTime] = useState("");
  const [level, setLevel] = useState<"" | "new" | "some" | "experienced">("");
  const [context, setContext] = useState("");
  const [clarAnswer, setClarAnswer] = useState("");
  const [autoMatch, setAutoMatch] = useState(false);

  const runAnalysis = (q: string) =>
    startAnalyze(async () => {
      const res = await analyzeQuestion(q);
      if (!res.ok) { setError(res.error); return; }
      setAnalysis(res.data);
      const first = res.data.suggestions.find((s) => !isHighStakes(s.topicId)) ?? res.data.suggestions[0];
      if (!props.initialTopic && first) setTopicId(first.topicId);
      if (!props.initialIntent) setIntent(res.data.intent);
      if (res.data.language) {
        const lang = props.languages.find((l) => l.split("-")[0] === res.data.language) ?? res.data.language;
        setLanguage(lang);
      }
    });

  useEffect(() => {
    if (step === 2 && question.trim().length >= 5 && !analysis) runAnalysis(question);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const safety = safetyCheck(question, topicId || undefined);
  const blocked = safety.kind === "emergency" || (topicId !== "" && isHighStakes(topicId));
  const canSubmit = question.trim().length >= 5 && topicId && formats.length > 0 && !blocked && (timing === "now" || preferredTime);

  const submit = () =>
    startSubmit(async () => {
      setError(null);
      const res = await createRequest({
        question, intent, topicId, language, formats, timing,
        preferredTime: timing === "later" && preferredTime ? new Date(preferredTime).toISOString() : null,
        experienceLevel: level, context, tags: analysis?.suggestions.map((s) => getTopic(s.topicId)?.name ?? s.topicId) ?? [],
        clarificationQuestion: analysis?.clarification ?? "", clarificationAnswer: clarAnswer, autoMatch,
      });
      if (!res.ok) return setError(res.error);
      router.push(`/requests/${res.data.id}`);
    });

  const languageOptions = [...new Set([...props.languages, ...Object.keys(LANGUAGES)])];

  if (step === 1) {
    return (
      <div className="mx-auto max-w-2xl">
        <PageHeader title="What are you trying to figure out?" subtitle="A sentence or two is plenty. You'll pick who to talk to next." />
        <form onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 5) setStep(2); }}>
          <Label htmlFor="question">Your question or goal</Label>
          <Textarea id="question" rows={4} maxLength={600} value={question} onChange={(e) => setQuestion(e.target.value)} autoFocus />
          {props.surprise && props.initialTopic && (
            <p className="mt-2 text-sm text-muted">Surprise pick from your interests: <strong>{getTopic(props.initialTopic)?.name}</strong>. Edit the starter question however you like.</p>
          )}
          {props.noneAvailable && <Notice tone="amber" className="mt-3">Nobody who fits is available right now for this topic. You can still send it and leave it for a later reply, or pick a time.</Notice>}
          <div className="mt-4 flex justify-end">
            <Button type="submit" disabled={question.trim().length < 5}>Continue</Button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <button onClick={() => setStep(1)} className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft size={16} aria-hidden /> Edit question
      </button>
      <PageHeader title="Let's find the right person" />

      <Card className="p-5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted">Your question</p>
        <p className="mt-1 font-display text-xl leading-snug">{question}</p>
      </Card>

      {safety.kind === "emergency" && (
        <Notice tone="rose" title="This sounds urgent — please reach out to emergency help now." className="mt-4">
          People isn&apos;t an emergency service and won&apos;t route this to volunteers. If you or someone else is in danger,
          call your local emergency number (911 in the US and Canada, 999 in the UK, 112 in the EU). In the US you can call
          or text 988 for the Suicide &amp; Crisis Lifeline. Elsewhere, findahelpline.com lists free local services.
        </Notice>
      )}

      <div className="mt-6 space-y-6">
        <section aria-labelledby="topic-h">
          <h2 id="topic-h" className="mb-2 font-semibold">Topic</h2>
          {analyzing && <Spinner label="Reading your question…" />}
          {analysis && analysis.suggestions.length > 0 && (
            <div className="mb-3">
              <p className="mb-2 flex items-center gap-1.5 text-sm text-muted">
                <Sparkles size={14} aria-hidden /> Suggested {analysis.source === "ai" ? "(AI-assisted)" : "from keywords"} — tap to choose, or pick below.
              </p>
              <div className="flex flex-wrap gap-2">
                {analysis.suggestions.map((s) => (
                  <Chip key={s.topicId} active={topicId === s.topicId} onClick={() => setTopicId(s.topicId)}>{topicPath(s.topicId)}</Chip>
                ))}
              </div>
            </div>
          )}
          {analysis && analysis.suggestions.length === 0 && <p className="mb-2 text-sm text-muted">We couldn&apos;t guess a topic — please choose one.</p>}
          <TopicPicker value={topicId} onChange={setTopicId} allowHighStakes />
          {topicId && isHighStakes(topicId) && (
            <Notice tone="amber" title="Professional advice isn't available in this pilot" className="mt-3">
              People can&apos;t present volunteers as qualified medical, legal or investment professionals, so these requests
              aren&apos;t matched. Please talk to a licensed professional. If you want to hear someone&apos;s personal
              experience instead (for example, what it was like to change careers), choose a different topic.
            </Notice>
          )}
          {topicId && isPerspective(topicId) && <Notice tone="indigo" className="mt-3">{RESPECT_NOTE}</Notice>}
        </section>

        {analysis?.clarification && (
          <section aria-labelledby="clar-h">
            <h2 id="clar-h" className="mb-2 font-semibold">One quick question <span className="font-normal text-muted">(optional)</span></h2>
            <Label htmlFor="clar">{analysis.clarification}</Label>
            <Input id="clar" value={clarAnswer} onChange={(e) => setClarAnswer(e.target.value)} maxLength={400} />
          </section>
        )}

        <section aria-labelledby="intent-h">
          <h2 id="intent-h" className="mb-2 font-semibold">Kind of help</h2>
          <div className="flex flex-wrap gap-2" role="group" aria-labelledby="intent-h">
            {INTENTS.map((it) => <Chip key={it.id} active={intent === it.id} onClick={() => setIntent(it.id)}>{it.label}</Chip>)}
          </div>
          <p className="mt-1.5 text-sm text-muted">{INTENTS.find((i) => i.id === intent)?.blurb}</p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="lang">Language</Label>
            <Select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {languageOptions.map((l) => <option key={l} value={l}>{LANGUAGES[l] ?? l}</option>)}
            </Select>
          </div>
          <div>
            <Label htmlFor="level" hint="(optional)">Your experience</Label>
            <Select id="level" value={level} onChange={(e) => setLevel(e.target.value as typeof level)}>
              <option value="">Prefer not to say</option>
              <option value="new">New to this</option>
              <option value="some">Some experience</option>
              <option value="experienced">Experienced</option>
            </Select>
          </div>
        </section>

        <section aria-labelledby="fmt-h">
          <h2 id="fmt-h" className="mb-2 font-semibold">How do you want to talk?</h2>
          <div className="flex flex-wrap gap-2" role="group" aria-labelledby="fmt-h">
            {FORMATS.map((f) => (
              <Chip
                key={f.id}
                active={formats.includes(f.id)}
                onClick={() => setFormats(formats.includes(f.id) ? formats.filter((x) => x !== f.id) : [...formats, f.id])}
              >{f.label}</Chip>
            ))}
          </div>
          <p className="mt-1.5 text-sm text-muted">Pick all you&apos;re comfortable with; the first is your preference. Cameras always start off.</p>
        </section>

        <section aria-labelledby="when-h">
          <h2 id="when-h" className="mb-2 font-semibold">When?</h2>
          <div className="flex flex-wrap gap-2" role="group" aria-labelledby="when-h">
            <Chip active={timing === "now"} onClick={() => setTiming("now")}>Now</Chip>
            <Chip active={timing === "later"} onClick={() => setTiming("later")}>At a set time</Chip>
          </div>
          {timing === "later" && (
            <div className="mt-3 max-w-xs">
              <Label htmlFor="when">Preferred time <span className="font-normal text-muted">(your local time)</span></Label>
              <Input id="when" type="datetime-local" value={preferredTime} onChange={(e) => setPreferredTime(e.target.value)} />
            </div>
          )}
        </section>

        <section>
          <Label htmlFor="ctx" hint="(optional)">Anything that would help them help you?</Label>
          <Textarea id="ctx" rows={3} maxLength={800} value={context} onChange={(e) => setContext(e.target.value)} placeholder="Background, what you've tried, what a good outcome looks like…" />
          <p className="mt-1 text-xs text-muted">Only the person you invite sees this. Don&apos;t include contact details.</p>
        </section>

        <label className="flex items-start gap-3 rounded-2xl border border-line bg-card p-4">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--color-indigo)]" checked={autoMatch} onChange={(e) => setAutoMatch(e.target.checked)} />
          <span>
            <span className="font-medium">Match me automatically</span>
            <span className="block text-sm text-muted">We&apos;ll invite the best-fitting available person, and the next one if they can&apos;t. You can still see who it is before you talk.</span>
          </span>
        </label>

        {error && <Notice tone="rose">{error}</Notice>}

        <div className="flex justify-end gap-3 pb-4">
          <Button size="lg" onClick={submit} disabled={!canSubmit || submitting}>
            {submitting ? "Finding people…" : autoMatch ? "Find a match" : "See who can help"}
          </Button>
        </div>
      </div>
    </div>
  );
}

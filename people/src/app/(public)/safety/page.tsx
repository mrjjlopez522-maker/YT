import { Card } from "@/components/ui";

export const metadata = { title: "Safety" };

const ITEMS: [string, string][] = [
  ["Invited adults only", "This pilot is for invited adults. Joining asks you to confirm you're 18+, which is a self-declaration, not real age verification."],
  ["Both people say yes", "A session only starts after you invite someone and they accept. Declining is always fine and nobody is told why."],
  ["Cameras start off", "Calls start with microphone only. Video is possible only after both people opt in, and either person can switch it off, stop receiving the other person's audio and video, or leave instantly."],
  ["Nothing is recorded", "Calls aren't recorded or transcribed, and no summaries are generated from audio or video. Text messages are kept so you can refer back, and so moderators can review a report."],
  ["Block and report", "Blocking ends any session with that person immediately and stops future matches both ways. Reports go to moderators, who can suspend accounts. Every moderator action is logged."],
  ["Not for emergencies", "If you or someone else is in danger, contact local emergency services. People won't route urgent requests to volunteers."],
  ["No professional advice", "Medical, legal and investment advice isn't offered. Helpers share personal or professional experience; only credentials marked \"reviewed by People\" were checked, and only for that topic."],
  ["Respectful perspectives", "Religion and culture conversations are personal perspectives, not official teaching. Ask with curiosity; it's always fine to say you'd rather not discuss something."],
  ["What isn't automated", "There's no automatic detection of nudity or abuse in calls. LiveKit carries media; it doesn't moderate it. Accepting video doesn't make a call safe — trust your judgment and leave whenever you want."],
];

export default function Safety() {
  return (
    <div>
      <h1 className="font-display text-4xl font-semibold">How People keeps conversations safe</h1>
      <p className="mt-2 text-ink-2">And, just as important, what it doesn&apos;t do yet.</p>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {ITEMS.map(([t, d]) => (
          <Card key={t} className="p-5"><h2 className="font-semibold">{t}</h2><p className="mt-1 text-sm leading-relaxed text-ink-2">{d}</p></Card>
        ))}
      </div>
    </div>
  );
}

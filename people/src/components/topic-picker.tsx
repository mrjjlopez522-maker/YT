"use client";

import { childTopics, getTopic, rootTopics, topicLineage } from "@/lib/domain/topics";
import { Label, Select } from "./ui";

/** Category → subtopic → specific, so people can correct a suggested tag. */
export function TopicPicker({ value, onChange, allowHighStakes = false, idPrefix = "topic" }: {
  value: string; onChange: (id: string) => void; allowHighStakes?: boolean; idPrefix?: string;
}) {
  const lineage = value ? topicLineage(value) : [];
  const roots = rootTopics().filter((t) => allowHighStakes || t.sensitivity !== "high_stakes");
  const levels: { options: { id: string; name: string }[]; selected: string; label: string }[] = [
    { options: roots, selected: lineage[0] ?? "", label: "Category" },
  ];
  if (lineage[0] && childTopics(lineage[0]).length)
    levels.push({ options: childTopics(lineage[0]), selected: lineage[1] ?? "", label: "Subtopic" });
  if (lineage[1] && childTopics(lineage[1]).length)
    levels.push({ options: childTopics(lineage[1]), selected: lineage[2] ?? "", label: "More specific" });

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {levels.map((lvl, i) => (
        <div key={i}>
          <Label htmlFor={`${idPrefix}-${i}`} hint={i > 0 ? "(optional)" : undefined}>{lvl.label}</Label>
          <Select
            id={`${idPrefix}-${i}`}
            value={lvl.selected}
            onChange={(e) => onChange(e.target.value || lineage[i - 1] || "")}
          >
            <option value="">{i === 0 ? "Choose…" : "Any"}</option>
            {lvl.options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </Select>
        </div>
      ))}
      {value && getTopic(value)?.description && <p className="text-xs text-muted sm:col-span-3">{getTopic(value)?.description}</p>}
    </div>
  );
}

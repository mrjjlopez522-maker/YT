"""Topic research providers.

LocalNotesProvider (offline): research notes you (or a researcher) wrote in
  your own words, each fact citing one or more sources. These can be narrated
  directly because the wording is yours.

WikipediaProvider (network): reads the article through the official APIs and
  stores sentences as *evidence*. Wikipedia prose is CC BY-SA, so it is never
  narrated verbatim (own_words = 0); a writer must restate it, and QC measures
  verbatim overlap.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import yaml

from ..errors import ProviderError
from ..http import HttpClient
from ..textutil import numbers_in, slugify, split_sentences


@dataclass
class Fact:
    text: str
    own_words: bool
    source_title: str | None
    source_url: str | None
    local_key: str | None = None
    tags: list[str] = field(default_factory=list)
    extra_sources: list[dict] = field(default_factory=list)
    fact_date: str | None = None
    question: str | None = None
    position: int = 0


@dataclass
class ResearchDoc:
    provider: str
    title: str
    url: str | None
    reliability: str
    content: str
    text_license: str | None = None
    facts: list[Fact] = field(default_factory=list)


@dataclass
class ResearchBundle:
    docs: list[ResearchDoc] = field(default_factory=list)
    hook_ideas: list[str] = field(default_factory=list)
    category: str | None = None


class ResearchProvider(ABC):
    name = "base"

    @abstractmethod
    def research(self, topic: str) -> ResearchBundle:
        ...


class LocalNotesProvider(ResearchProvider):
    name = "local_notes"

    def __init__(self, notes_dir: Path):
        self.notes_dir = Path(notes_dir)

    def find(self, topic: str) -> Path | None:
        slug = slugify(topic)
        direct = self.notes_dir / f"{slug}.yaml"
        if direct.is_file():
            return direct
        if self.notes_dir.is_dir():
            for path in sorted(self.notes_dir.glob("*.y*ml")):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    continue
                if slugify(str(data.get("topic", ""))) == slug:
                    return path
        return None

    def research(self, topic: str) -> ResearchBundle:
        path = self.find(topic)
        if path is None:
            return ResearchBundle()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ProviderError(f"Research notes {path} are not valid YAML: {exc}") from exc
        sources = {s["id"]: s for s in data.get("sources", []) if "id" in s}
        docs: dict[str, ResearchDoc] = {}
        for sid, s in sources.items():
            docs[sid] = ResearchDoc(provider=self.name, title=s.get("title") or sid, url=s.get("url"),
                                    reliability=s.get("reliability", "user_notes"),
                                    content=f"notes file: {path.name}")
        errors = []
        for pos, f in enumerate(data.get("facts", [])):
            cited = [c for c in f.get("sources", []) if c in sources]
            if not f.get("text") or not cited:
                errors.append(f.get("id", "?"))
                continue
            primary = sources[cited[0]]
            fact = Fact(text=f["text"].strip(), own_words=True, source_title=primary.get("title"),
                        source_url=primary.get("url"), local_key=f.get("id"), tags=list(f.get("tags") or []),
                        extra_sources=[{"title": sources[c].get("title"), "url": sources[c].get("url")} for c in cited[1:]],
                        fact_date=str(f["date"]) if f.get("date") else None, question=f.get("question"),
                        position=pos)
            docs[cited[0]].facts.append(fact)
        if errors:
            raise ProviderError(f"Facts without text or a valid citation in {path.name}: {errors}",
                                hint="every fact needs `text` and at least one `sources` id defined under `sources`")
        return ResearchBundle(docs=list(docs.values()), hook_ideas=list(data.get("hook_ideas") or []),
                              category=data.get("category"))


class WikipediaProvider(ResearchProvider):
    name = "wikipedia"

    def __init__(self, http: HttpClient, lang: str = "en", max_facts: int = 30):
        self.http = http
        self.lang = lang
        self.max_facts = max_facts
        self.api = f"https://{lang}.wikipedia.org/w/api.php"

    def research(self, topic: str) -> ResearchBundle:
        search = self.http.get_json(self.api, params={"action": "query", "list": "search", "srsearch": topic,
                                                      "srlimit": "1", "format": "json", "formatversion": "2"})
        hits = search.get("query", {}).get("search", [])
        if not hits:
            return ResearchBundle()
        title = hits[0]["title"]
        data = self.http.get_json(self.api, params={"action": "query", "prop": "extracts|info", "explaintext": "1",
                                                    "inprop": "url", "titles": title, "redirects": "1",
                                                    "format": "json", "formatversion": "2"})
        pages = data.get("query", {}).get("pages", [])
        if not pages or "extract" not in pages[0]:
            return ResearchBundle()
        page = pages[0]
        url = page.get("fullurl") or f"https://{self.lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        text = re.split(r"\n==\s*(See also|References|Notes|External links|Further reading)\s*==", page["extract"])[0]
        facts = []
        for sent in split_sentences(text.replace("\n", " ")):
            if 8 <= len(sent.split()) <= 45 and (numbers_in(sent) or re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", sent)):
                facts.append(Fact(text=sent, own_words=False, source_title=f"{title} (Wikipedia)", source_url=url,
                                  position=len(facts)))
            if len(facts) >= self.max_facts:
                break
        doc = ResearchDoc(provider=self.name, title=f"{title} (Wikipedia)", url=url, reliability="tertiary",
                          content=text, text_license="CC-BY-SA-4.0", facts=facts)
        return ResearchBundle(docs=[doc])


def build_research_providers(ctx, names: list[str] | None = None) -> list[ResearchProvider]:
    names = names or ctx.cfg.get("research.providers")
    registry = {
        "local_notes": lambda: LocalNotesProvider(ctx.cfg.path(ctx.cfg.get("research.notes_dir"))),
        "wikipedia": lambda: WikipediaProvider(ctx.http, lang=ctx.cfg.get("channel.language")),
    }
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise ProviderError(f"Unknown research providers in config: {unknown}")
    return [registry[n]() for n in names]

"""Static, self-contained HTML pages: the per-video review page and the performance dashboard."""
from __future__ import annotations

import html
import os
from pathlib import Path

from ..textutil import now_iso

CSS = """
:root{--bg:#f7f7f5;--fg:#1b1d22;--muted:#5d6470;--card:#fff;--line:#e3e4e8;--ok:#127a3e;--bad:#b3261e;--warn:#9a6700;--accent:#1f6feb}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1115;--fg:#e8eaef;--muted:#a0a7b4;--card:#171a21;--line:#2a2f3a;--ok:#4cc38a;--bad:#ff6b6b;--warn:#e3b341;--accent:#58a6ff}}
:root[data-theme="dark"]{--bg:#0f1115;--fg:#e8eaef;--muted:#a0a7b4;--card:#171a21;--line:#2a2f3a;--ok:#4cc38a;--bad:#ff6b6b;--warn:#e3b341;--accent:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:minmax(0,340px) minmax(0,1fr);gap:24px}
@media (max-width:760px){.grid{grid-template-columns:minmax(0,1fr)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;overflow-wrap:anywhere}
video{width:100%;border-radius:10px;background:#000;aspect-ratio:9/16}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;border:1px solid currentColor}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}code,pre{font:13px ui-monospace,Menlo,Consolas,monospace}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto}
.sec{font-size:12px;font-weight:700;letter-spacing:.06em;color:var(--muted);margin-top:10px}.thumbs{display:flex;gap:8px;flex-wrap:wrap}
.thumbs img{width:96px;border-radius:6px;border:1px solid var(--line)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi b{display:block;font-size:22px}
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def _rel(target: str | Path, start: Path) -> str:
    return os.path.relpath(str(target), str(start))


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{_e(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main></body></html>")


def write_review_page(ctx, video_id: str) -> Path:
    db = ctx.db
    v = db.require("videos", video_id)
    topic = db.require("topics", v["topic_id"])
    script = db.get("scripts", v["script_id"]) if v.get("script_id") else {}
    claims = db.select("claims", {"script_id": v["script_id"]}) if v.get("script_id") else []
    scenes = db.select("scenes", {"video_id": video_id}, order_by="idx")
    used = {s["visual_source"] for s in scenes if s.get("visual_source")}
    rights = db.query("SELECT * FROM source_rights WHERE source_id IN (%s)" % ",".join("?" * len(used)), list(used)) \
        if used else []
    lic_rows = {r["source_id"]: r for r in db.query(
        "SELECT * FROM licenses WHERE source_id IN (%s)" % ",".join("?" * len(used)), list(used))} if used else {}
    thumbs = db.select("assets", {"video_id": video_id, "kind": "thumbnail"})
    qc = v.get("qc_report_json") or {}
    md = v.get("metadata_json") or {}
    out_dir = ctx.ws.export_dir(v["base_name"])
    out_dir.mkdir(parents=True, exist_ok=True)

    qc_rows = "".join(
        f"<tr><td>{_e(c['name'])}</td><td><span class='pill {'ok' if c['passed'] else ('warn' if c['severity'] == 'warning' else 'bad')}'>"
        f"{'PASS' if c['passed'] else 'FAIL'}</span></td><td>{_e(c['details'])}</td></tr>" for c in qc.get("checks", []))
    script_html = "".join(
        f"<div class='sec'>{_e(sec['name'])}</div>" + "".join(f"<p>{_e(x['text'])}</p>" for x in sec["sentences"])
        for sec in (script.get("sections_json") or []))
    hooks = "".join(f"<tr><td>{_e(h['score'])}</td><td>{_e(h['strategy'])}</td><td>{_e(h['text'])}</td></tr>"
                    for h in (script.get("hooks_json") or []))
    titles = "".join(f"<li>{_e(t['title'])} <span class='muted'>({t['score']})</span></li>" for t in md.get("titles", []))
    claim_rows = "".join(
        f"<tr><td>{_e(c['claim'])}</td><td><span class='pill {'ok' if c['status'] == 'VERIFIED' else 'bad'}'>"
        f"{_e(c['status'])}</span></td><td>{_e(c['confidence'])}</td><td>"
        f"{('<a href=' + chr(34) + _e(c['source_url']) + chr(34) + '>' + _e(c['source']) + '</a>') if c.get('source_url') else _e(c.get('source'))}"
        f"</td></tr>" for c in claims)
    rights_rows = "".join(
        f"<tr><td><code>{_e(r['source_id'])}</code><br>{_e(r['title'])}<br><span class='muted'>{_e(r['creator'])} · "
        f"{_e(r['platform'])}</span></td><td>{_e(r['license_type'])}</td><td>commercial: {_e(r['commercial_use_allowed'])}"
        f"<br>modify: {_e(r['modification_allowed'])}<br>attribution: {_e(r['attribution_required'])}</td>"
        f"<td>{_e(r['permission_reference'])}<br>{_e(r['permission_date'])}</td><td>{_e(r['rights_confidence'])}"
        f"<br><span class='muted'>{_e(lic_rows.get(r['source_id'], {}).get('verified_by'))}</span></td></tr>"
        for r in rights)
    scene_rows = "".join(
        f"<tr><td>{s['start_time']:.1f}–{s['end_time']:.1f}</td><td>{_e(s['section'])}</td><td>{_e(s['visual_type'])}"
        f"<br><code>{_e(s.get('visual_source') or '')}</code></td><td>{_e(s.get('effect'))}</td>"
        f"<td>{_e(', '.join(g['type'] for g in (s.get('graphics_json') or [])))}</td></tr>" for s in scenes)
    risk = "".join(f"<li>{_e(r)}</li>" for r in qc.get("risk_flags", [])) or "<li>none</li>"
    thumb_html = "".join(f"<img src='{_e(_rel(t['path'], out_dir))}' alt='thumbnail concept {i}'>"
                         for i, t in enumerate(thumbs, 1))
    render_rel = _rel(v["render_path"], out_dir) if v.get("render_path") else ""
    vid = _e(video_id)
    body = f"""
<h1>{_e(v.get('selected_title') or topic['topic'])}</h1>
<div class='muted'>{vid} · status <b>{_e(v['status'])}</b> · QC <b class='{'ok' if qc.get('passed') else 'bad'}'>{'PASSED' if qc.get('passed') else 'FAILED'}</b> · generated {now_iso()}</div>
<div class='grid' style='margin-top:18px'>
  <div><video controls preload='metadata' src='{_e(render_rel)}'></video>
    <h2>Thumbnail concepts</h2><div class='thumbs'>{thumb_html}</div></div>
  <div>
    <div class='card'><b>Decide</b> (manual approval is required; nothing is uploaded from this page)
<pre>python main.py review --video {vid} --approve [--allow-public]
python main.py review --video {vid} --reject --notes "why"
python main.py review --video {vid} --edit-title "..." --edit-description-file desc.txt
python main.py review --video {vid} --edit-script script.yaml
python main.py review --video {vid} --render-again
python main.py review --video {vid} --schedule 2026-10-02T15:00:00Z --allow-public</pre></div>
    <h2>Risk flags</h2><div class='card'><ul>{risk}</ul></div>
    <h2>Title options</h2><div class='card'><ol>{titles}</ol></div>
    <h2>Description</h2><div class='card'><pre>{_e(v.get('selected_description'))}</pre></div>
  </div>
</div>
<h2>Script <span class='muted'>({_e(script.get('word_count'))} words · {_e(script.get('format'))} · writer {_e(script.get('llm_provider'))})</span></h2>
<div class='card'>{script_html}<div class='sec'>ANGLE</div><p>{_e(script.get('angle'))}</p></div>
<h2>Hook candidates (scored)</h2><div class='card'><table><tr><th>score</th><th>strategy</th><th>hook</th></tr>{hooks}</table></div>
<h2>Fact sources</h2><div class='card'><table><tr><th>claim</th><th>status</th><th>conf.</th><th>source</th></tr>{claim_rows}</table></div>
<h2>Sources &amp; license information</h2><div class='card'><table><tr><th>source</th><th>license</th><th>permissions</th><th>reference</th><th>confidence</th></tr>{rights_rows or '<tr><td colspan=5>original graphics only</td></tr>'}</table></div>
<h2>QC</h2><div class='card'><table>{qc_rows}</table></div>
<h2>Storyboard</h2><div class='card'><table><tr><th>time</th><th>section</th><th>visual</th><th>effect</th><th>graphics</th></tr>{scene_rows}</table></div>
"""
    path = out_dir / "review.html"
    path.write_text(_page(f"Review {video_id}", body), encoding="utf-8")
    ctx.db.delete("assets", {"video_id": video_id, "kind": "review_page"})
    from ..textutil import new_id
    ctx.db.insert("assets", {"asset_id": new_id("ast"), "video_id": video_id, "kind": "review_page", "path": str(path),
                             "created_at": now_iso()})
    return path


def write_dashboard(ctx, data: dict) -> Path:
    """Performance dashboard from analytics.dashboard_data(). Descriptive only."""
    k = data["kpis"]

    def kpi(label, value):
        return f"<div class='card kpi'><span class='muted'>{_e(label)}</span><b>{_e(value)}</b></div>"
    kpis = "".join([kpi("Total videos", k["total_videos"]), kpi("Published", k["published"]),
                    kpi("Total views", k["total_views"]), kpi("Average views", k["average_views"]),
                    kpi("Avg % viewed", k["average_retention"]), kpi("Subscribers gained", k["subscribers_gained"]),
                    kpi("Uploads / week (last 4w)", k["publishing_per_week"]),
                    kpi("Revenue (actual)", k["revenue_actual"])])

    def table(rows, cols):
        head = "".join(f"<th>{_e(c)}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{_e(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows)
        return f"<table><tr>{head}</tr>{body or '<tr><td colspan=9 class=muted>no data yet</td></tr>'}</table>"
    working = "".join(f"<li>{_e(x)}</li>" for x in data["what_is_working"]) or "<li>no data yet</li>"
    body = f"""
<h1>Channel performance</h1><div class='muted'>Generated {now_iso()} · descriptive analytics only — patterns here are correlations, not causes.</div>
<h2>Overview</h2><div class='kpis'>{kpis}</div>
<h2>What is working? (descriptive)</h2><div class='card'><ul>{working}</ul></div>
<h2>By topic</h2><div class='card'>{table(data['by_topic'], ['topic', 'videos', 'views', 'avg_views', 'avg_pct_viewed'])}</div>
<h2>By content format</h2><div class='card'>{table(data['by_format'], ['format', 'videos', 'views', 'avg_views', 'avg_pct_viewed'])}</div>
<h2>Videos</h2><div class='card'>{table(data['videos'], ['video_id', 'status', 'title', 'views', 'avg_pct_viewed', 'subscribers_gained'])}</div>
<h2>Costs (estimates)</h2><div class='card'><pre>{_e(data['costs'])}</pre></div>
<h2>Revenue</h2><div class='card'><pre>{_e(data['revenue'])}</pre></div>
"""
    path = ctx.ws.dir("exports") / "dashboard.html"
    path.write_text(_page("Channel performance", body), encoding="utf-8")
    return path

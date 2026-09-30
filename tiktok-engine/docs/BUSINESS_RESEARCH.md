# TikTok monetization and API: research notes

Researched: 2026-09-30.

**Method:** web search of official TikTok sources (`tiktok.com`,
`support.tiktok.com`, `newsroom.tiktok.com`, `developers.tiktok.com`),
cross-checked with independent coverage. Direct page fetches were blocked in
the development environment, so every item is **[search-verified]**: it is
consistent across search results but has not yet been read on the primary
page. Re-read the linked pages before making decisions; programs change often.

Labels used in this document:

- **VERIFIED FACT:** stated by TikTok (search-verified).
- **ESTIMATE:** derived, with the method given.
- **ASSUMPTION:** a planning input you should replace with your own data.

## VERIFIED FACT: Creator Rewards Program

- **Account requirements:** 18 or older, at least 10,000 followers, and at least
  100,000 video views in the last 30 days. The account must be a Personal
  Account in good standing; business, organisation, political, and government
  accounts are excluded. [search-verified]
- **Eligible countries (listed):** US, UK, Germany, Japan, South Korea, France,
  Mexico, Brazil. [search-verified]
- **Video requirements:** original, high-quality, and **at least 1 minute
  long**, posted publicly. At least 1,000 For You feed views. Duets, Stitches,
  Photo Mode, ads, and sponsored content do not qualify. [search-verified]

Sources:

- https://www.tiktok.com/creator-academy/article/eligibility
- https://www.tiktok.com/creator-academy/article/creator-rewards-program
- https://support.tiktok.com/en/business-and-creator/creator-rewards-program/creator-rewards-program
- https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en

## VERIFIED FACT: other revenue routes

- **TikTok Shop affiliate (US):** 18 or older, US-based, and at least 1,000
  followers to apply. Accounts under 5,000 followers usually start in a pilot
  period (sources report 30 days). Commerce policies apply. [search-verified;
  mostly third-party summaries — confirm in TikTok Shop Academy]
- **Brand deals, affiliate links, your own products, and lead generation:**
  these follow the platform's branded content rules. Paid partnerships must
  be disclosed with the branded content toggle. [policy, search-verified]

## VERIFIED FACT: US entity (context)

- **New ownership:** since 2026-01-22, TikTok's US operations are controlled by
  TikTok USDS Joint Venture LLC. That entity handles US data, trust and
  safety, and moderation. Commercial operations such as ads, Shop, and payouts
  remained with ByteDance, and reports say creator payouts did not change.
  [search-verified]
- **Source:** https://newsroom.tiktok.com/announcement-from-the-new-tiktok-usds-joint-venture-llc?lang=en

## VERIFIED FACT: APIs this engine may and may not use

| Need | Official route | Constraint |
|---|---|---|
| Publish | **Content Posting API** (Direct Post: `video.publish`; Upload to drafts: `video.upload`), OAuth 2.0 | **Unaudited apps can only post `SELF_ONLY` (private).** Public posting needs TikTok's app audit. Before posting you must query `creator_info`, offer only the returned `privacy_level_options`, and have the user pick privacy manually with **no default**. Interaction toggles disabled by `creator_info` must be greyed out. [search-verified] |
| Own video stats | **Display API** `video.list` / `video.query` (`user.info.basic`, `video.list` scopes) | Fields include view/like/comment/share counts, duration, and cover. Watch time, completion, retention, saves, and traffic sources are **not** in these fields; import them from TikTok Studio analytics exports or enter them manually. [search-verified] |
| Platform-wide trend data | **Research API** | **Academic and non-profit research only; commercial use is prohibited.** This engine does not use it. [search-verified] |
| Trending hashtags and ads | TikTok **Creative Center** (web UI) | No official public commercial API. Third-party "Creative Center APIs" are scrapers, which this engine does not use. You can record your own observations manually. [search-verified] |

Sources:

- https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video
- https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list
- https://developers.tiktok.com/products/research-api

## VERIFIED FACT: AI-generated content

TikTok **requires** a label on AI-generated content that contains realistic
images, audio, or video. Labelling fully AI-generated content is encouraged
otherwise. You can disclose with the AIGC label, a sticker, or the caption.
TikTok may also auto-label content via C2PA Content Credentials.
[search-verified]

**Consequence for this engine:**

- The narration is always synthetic, and a TTS voice can sound realistic, so
  the engine discloses synthetic narration in the caption by default
  (`publishing.disclose_synthetic_voice`).
- Procedural graphics such as fractals, charts, and cards are not
  "realistic", but disclosure is still configurable.

Sources:

- https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content
- https://newsroom.tiktok.com/en-us/new-labels-for-disclosing-ai-generated-content

## What this means for the plan (ESTIMATE / ASSUMPTION)

1. **ESTIMATE:** Creator Rewards pays nothing for videos under 60 seconds.
   The engine's default target length is therefore **65 s** for monetizable
   formats; 15–45 s formats remain available for reach experiments. Retention
   on longer videos must earn that length. The QC gate checks pacing, not just
   duration.
2. **ESTIMATE:** a new account starts ineligible for Creator Rewards (it needs
   10k followers and 100k views in 30 days). The finance model shows $0 from
   Creator Rewards until you record actual eligibility.
3. **ASSUMPTION:** early revenue is more plausible from sponsorships,
   affiliates, and cross-posting (for example, YouTube Shorts via the existing
   `studio` engine) than from Creator Rewards. None of these is promised. The
   finance module only uses revenue you record.
4. **FACT-derived:** publishing through the API is private-only until TikTok
   audits your app. Until then, plan on the **Upload (drafts)** route or
   `SELF_ONLY` posts that you make public in the app yourself.

## Open questions to verify on primary pages

- The Creator Rewards "qualified view" definition and the per-country rate
  basis.
- The current `post_info` fields in the Direct Post reference: title length
  limit and whether an AIGC flag exists in the API. Until confirmed, the
  engine discloses in the caption.
- Content Posting API rate limits and daily post caps per user for your app.

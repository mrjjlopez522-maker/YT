# Business Research: YouTube Partner Program and Shorts Monetization

Researched: 2026-09-30.

**Method:** web search restricted to `support.google.com` and `blog.youtube`,
cross-checked against independent coverage. Direct page fetches from
`support.google.com` and `blog.youtube` were blocked by the development
environment's egress policy, so each item below is marked **[search-verified]**:
it is consistent across several search results but has not yet been read on
the primary page. **Re-read the linked official pages before you make any
financial decision.** Policies change.

Labels used in this document:

- **FACT:** stated by an official YouTube source (search-verified).
- **ESTIMATE:** derived from data, with the method given.
- **ASSUMPTION:** a planning input you should replace with your own data.

## FACT: current YPP eligibility (until 2027-01-31)

- **Ads and Premium revenue:** 1,000 subscribers **and** either 4,000 public
  watch hours in the last 12 months **or** 10M qualified public Shorts views in
  the last 90 days. [search-verified]
  Sources: https://support.google.com/youtube/answer/72851
- **Expanded YPP (fan funding only):** 500 subscribers, 3 valid public uploads
  in the last 90 days, **and** either 3,000 watch hours in the last 12 months
  **or** 3M qualified Shorts views in the last 90 days. This tier unlocks
  memberships, Super Chat/Stickers/Thanks, and Shopping, **not** ad revenue.
  It is available only in rollout countries. [search-verified]
  Source: https://support.google.com/youtube/answer/13429240
- **Qualified Shorts views** must come from public Shorts and be *engaged
  views*: the viewer watches past the first seconds, and loops are excluded.
  [search-verified]
  Source: https://blog.youtube/news-and-events/youtube-monetization-qualified-watch-hours-shorts-views/

## FACT: announced changes effective 2027-02-01

YouTube announced these on 2026-08-10:

- **New applicants:** 8,000 watch hours in 365 days **or** 20M qualified Shorts
  views in 90 days. The 1,000-subscriber requirement is unchanged.
  [search-verified]
- **New floor for all partners, including existing ones:** 10M qualified
  Shorts views in a rolling 90 days to receive the monthly Shorts ad and
  Premium revenue share. [search-verified]
- **Existing partners** keep YPP status but must accept the updated terms by
  2027-01-31. [search-verified]
- **New incentive programs** for channels below the threshold: milestone
  bonuses, Shopping bonuses, brand-deal incentives, and trend boosts.
  [search-verified]

Sources:

- https://blog.youtube/news-and-events/youtube-partner-program-updates-2027-new-opportunities-earn/
- https://support.google.com/youtube/answer/12843009
- Independent coverage: https://www.tubefilter.com/2026/08/10/youtube-partner-program-ad-eligibility-requirements-shorts/

## FACT: how Shorts revenue sharing works

- Ad revenue from the Shorts Feed is pooled monthly. Part of the pool pays for
  music licensing, and the rest (the Creator Pool) is allocated by each
  creator's share of engaged views in each country. Creators keep **45%** of
  their allocation. [search-verified]
  Source: https://support.google.com/youtube/answer/12504220
- **Music reduces the Creator Pool share:** one track sends half of that
  Short's revenue to music licensing, and two tracks send two thirds.
  **Consequence for this system:** music is off by default (`music_policy: none`).
  [search-verified]
- **Ineligible views:** views on non-original Shorts, such as unedited clips
  from films or TV, re-uploads, or compilations with no original content, are
  ineligible. The "repetitious content" policy was renamed "inauthentic
  content" on 2025-07-15. "Reused content" means content without significant
  original commentary, substantive modification, or educational or
  entertainment value. [search-verified]
  Sources: https://support.google.com/youtube/answer/1311392,
  https://support.google.com/youtube/answer/12504220

## What this means for the plan (ESTIMATE / ASSUMPTION, not FACT)

1. **Shorts ad revenue is unlikely to be the first revenue stream.**
   (ESTIMATE) From 2027-02-01, Shorts ad revenue requires sustaining 10M
   qualified views every 90 days, about 111k per day. A new channel should plan
   for $0 Shorts ad revenue until the analytics show it is near that level.
   The finance model defaults to $0 Shorts ad revenue unless eligibility is
   explicitly asserted.
2. **Evaluate these streams in parallel.** (ASSUMPTION)
   - Long-form expansion, where the watch-hours path applies.
   - Sponsorships and brand integrations.
   - Affiliate links, a newsletter, and digital products.
   - The new YouTube incentive programs.
   None of these are promised, and each needs its own data.
3. **Originality is a monetization requirement, not just an ethical choice.**
   (FACT-derived) The reused and inauthentic content policies make views on
   non-transformative Shorts ineligible. This is why the rights, originality,
   and QC gates exist.
4. **No RPM figure is assumed anywhere in this codebase.** The finance module
   accepts actual revenue data. Hypothetical scenarios require you to type the
   RPM yourself, and the output is labelled `HYPOTHETICAL`.

## Open questions to verify against primary pages

- The exact eligibility wording and country availability for your channel's
  country.
- Whether the 2027 Shorts floor counts views across all of a channel's Shorts
  (as reported) and how it treats partial months.
- The current `videos.insert` API quota cost and the daily quota for your
  Google Cloud project, which determines the maximum number of uploads per day.
- Whether the `status.containsSyntheticMedia` Data API field is available to
  your project, and the current altered/synthetic content disclosure rules for
  synthetic narration.

#!/usr/bin/env bash
# Builds with fake secret values and fails if any appear in browser bundles.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf .next
DATABASE_URL="postgres://u:FAKESECRETDB@db.invalid/x" \
LIVEKIT_URL=wss://lk.invalid LIVEKIT_API_KEY=FAKELKKEY LIVEKIT_API_SECRET=FAKELKSECRET \
ANTHROPIC_API_KEY=sk-ant-FAKEAIKEY \
NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=public-anon-key \
  npx next build > /dev/null
if grep -rlE "FAKESECRETDB|FAKELKKEY|FAKELKSECRET|FAKEAIKEY" .next/static; then
  echo "FAIL: a server secret reached browser code" >&2; exit 1
fi
echo "OK: no server secrets in .next/static"
rm -rf .next

#!/usr/bin/env bash
set -euo pipefail
# OPTIONAL: clones source for inspection, but DOES NOT install dependencies, models,
# write wallets, start networks, or use money. Record commit SHA and verify license.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/external-src"
mkdir -p "$DEST"
for entry in \
  'orbit|https://github.com/wlanderson0/orbit.git' \
  'inspect_ai|https://github.com/UKGovernmentBEIS/inspect_ai.git' \
  'colosseum|https://github.com/umass-ai-safety/colosseum.git' \
  'erc8183|https://github.com/erc-8183/base-contracts.git' \
  'x402|https://github.com/x402-foundation/x402.git'; do
  NAME="${entry%%|*}"
  URL="${entry#*|}"
  if [[ -d "$DEST/$NAME/.git" ]]; then
    echo "EXISTS: $NAME (not pulling automatically)"
  else
    echo "CLONING: $NAME $URL"
    git clone --filter=blob:none "$URL" "$DEST/$NAME"
  fi
  (cd "$DEST/$NAME" && printf '%s ' "$NAME" && git rev-parse HEAD)
done
printf '\nNOT INSTALLED. Verify releases, licenses, upstream README and commit pins before running third-party code.\n'

#!/usr/bin/env bash
set -euo pipefail

INDEX_URL="http://ndclnh-mytho-usa.org/Tuan%20Bao%20Doi%20Moi.htm"
OUT_DIR="${1:-/Users/danntran/Repos.nosync/viet-print-index/data/doi-moi}"

mkdir -p "$OUT_DIR"

echo "Fetching index..."
urls=$(curl -s --max-time 30 "$INDEX_URL" \
  | grep -oi 'href="[^"]*\.pdf[^"]*"' \
  | sed 's/href="//;s/"//')

total=$(echo "$urls" | wc -l | tr -d ' ')
count=0
failed=0

while IFS= read -r url; do
  count=$((count + 1))
  name=$(basename "$url" | sed 's/%20/ /g')
  dest="$OUT_DIR/$name"

  if [[ -f "$dest" ]]; then
    echo "[$count/$total] Skip: $name"
    continue
  fi

  echo "[$count/$total] Downloading: $name"
  if ! curl -L --retry 3 --retry-delay 5 --max-time 120 -o "$dest" "$url"; then
    echo "FAILED: $url"
    rm -f "$dest"
    failed=$((failed + 1))
  fi
done <<< "$urls"

echo ""
echo "Done. $((count - failed)) downloaded, $failed failed."

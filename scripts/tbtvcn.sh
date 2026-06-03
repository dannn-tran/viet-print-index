#!/bin/bash

set -euo pipefail

URL="http://ndclnh-mytho-usa.org/Trung%20Bac%20Tan%20Van%20Chu%20Nhat.htm"

# Change this to wherever you want the files saved
OUTDIR="data/tbtvcn/pdf"

mkdir -p "$OUTDIR"

echo "Fetching PDF list..."

curl -s "$URL" |
grep -oiE 'href="[^"]+\.pdf"' |
sed -E 's/href="(.*)"/\1/i' |
sort -u |
while read -r pdf_url; do
    filename=$(basename "$pdf_url")

    # Skip existing files
    if [ -f "$OUTDIR/$filename" ]; then
        echo "Skipping existing: $filename"
        continue
    fi

    echo "Downloading: $filename"
    curl -L --fail \
         -o "$OUTDIR/$filename" \
         "$pdf_url"
done

echo "Finished. Files saved to:"
echo "$OUTDIR"

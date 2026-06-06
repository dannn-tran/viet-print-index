#!/bin/bash

set -euo pipefail

BASE_URL="http://ndclnh-mytho-usa.org"

download_pdfs() {
    local url="$1"
    local outdir="$2"

    mkdir -p "$outdir"

    echo "Fetching PDF list from: $url"

    curl -s "$url" |
    grep -oiE 'href="[^"]+\.pdf"' |
    sed -E 's/href="(.*)"/\1/i' |
    sort -u |
    while read -r pdf_url; do
        # Resolve relative URLs
        if [[ "$pdf_url" != http* ]]; then
            pdf_url="$BASE_URL/$pdf_url"
        fi

        filename=$(basename "$pdf_url")

        if [ -f "$outdir/$filename" ]; then
            echo "Skipping existing: $filename"
            continue
        fi

        echo "Downloading: $filename"
        curl -L --fail \
             -o "$outdir/$filename" \
             "$pdf_url"
    done

    echo "Done: $outdir"
}

download_pdfs "$BASE_URL/bachkhoa.htm"                    "data/bachkhoa/pdf"
download_pdfs "$BASE_URL/Van%20Hoa%20Nguet%20San.htm"    "data/van-hoa-nguet-san/pdf"
download_pdfs "$BASE_URL/Nam%20Phong%20Tap%20Chi.htm"    "data/nam-phong-tap-chi/pdf"

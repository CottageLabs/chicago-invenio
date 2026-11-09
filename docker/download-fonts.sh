#!/usr/bin/env bash
# Download the UChicago brand fonts into assets/fonts so webpack can bundle them.
# The fonts are not committed to this (public) repository; the Docker build runs
# this script, and for local development run it once before building assets.
#
# Usage: docker/download-fonts.sh [assets-dir]   (default: ./assets)
set -euo pipefail

ASSETS_DIR="${1:-./assets}"
BASE_URL="https://uchicago-brand-fonts.s3.us-east-2.amazonaws.com/fonts/uchicago-sans-serif"
DEST="${ASSETS_DIR}/fonts/uchicago-sans-serif"

mkdir -p "${DEST}"
for face in Light LightItalic Regular RegularItalic SemiBold SemiBoldItalic Bold BoldItalic; do
    curl -fsSL --retry 3 -o "${DEST}/UChicagoSansSerif-${face}.woff2" \
        "${BASE_URL}/UChicagoSansSerif-${face}.woff2"
done

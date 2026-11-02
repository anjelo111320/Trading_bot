#!/bin/sh
# Fails if a secret or a server-only setting reached the browser bundle.
set -eu
bundle=frontend/.next/static
[ -d "$bundle" ] || { echo "No build found. Run pnpm build first."; exit 1; }
key=$(sed -n 's/^APP_SECRET_KEY=//p' .env)
for needle in "$key" local_dev_only ANTHROPIC_API_KEY APP_SECRET_KEY DATABASE_URL REDIS_URL; do
  [ -n "$needle" ] || continue
  if grep -rqF -- "$needle" "$bundle"; then
    echo "Found a server-only value in the browser bundle."
    exit 1
  fi
done
echo "Bundle scan clean."

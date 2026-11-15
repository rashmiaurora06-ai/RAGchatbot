#!/bin/zsh
# Saves your Groq API key into .env without showing it on screen.
cd "$(dirname "$0")" || exit 1
[ -f .env ] || cp .env.example .env
read -s "K?Paste your Groq key (nothing will show), then press Enter: "
echo
K="${K//[[:space:]]/}"
if [[ "$K" != gsk_* ]]; then
  echo "That doesn't look like a Groq key (it should start with gsk_). Nothing was saved."
  exit 1
fi
if grep -q "^GROQ_API_KEY=" .env; then
  sed -i '' "s|^GROQ_API_KEY=.*|GROQ_API_KEY=$K|" .env
else
  echo "GROQ_API_KEY=$K" >> .env
fi
unset K
grep -q "^GROQ_API_KEY=gsk_" .env && echo "Saved. Key is set." || echo "Something went wrong; key not saved."

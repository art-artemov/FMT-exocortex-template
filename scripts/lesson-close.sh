#!/usr/bin/env bash
# routing: executor=script  deterministic=true  skill=lesson-close  optimization_priority=2
# see DP.SC.159, DP.ROLE.059
# lesson-close.sh — закрыть занятие в дневном файле (lesson/<date>.md)
#
# Usage: lesson-close.sh [YYYY-MM-DD] [--no-push]

set -euo pipefail

DATE="${1:-$(date +%Y-%m-%d)}"
NO_PUSH="${2:-}"
FILE="lesson/${DATE}.md"

if [[ ! -f "$FILE" ]]; then
  echo "ERROR: lesson file not found: $FILE" >&2
  exit 1
fi

# Обновляем frontmatter через Python
python3 <<PYEOF
import yaml, re, sys
from datetime import datetime

with open("$FILE", "r") as f:
    content = f.read()

# Разделяем frontmatter и тело
m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
if not m:
    print("ERROR: invalid frontmatter", file=sys.stderr)
    sys.exit(1)

fm = yaml.safe_load(m.group(1))
body = m.group(2)

fm["status"] = "done"
fm["finished_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

# Расчёт duration_min если есть started_at
if "started_at" in fm and fm["started_at"]:
    try:
        start = datetime.fromisoformat(fm["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(fm["finished_at"].replace("Z", "+00:00"))
        fm["duration_min"] = int((end - start).total_seconds() / 60)
    except Exception:
        pass

new_fm = yaml.dump(fm, allow_unicode=True, sort_keys=False)
new_content = f"---\n{new_fm}---\n{body}"

with open("$FILE", "w") as f:
    f.write(new_content)

print(f"Updated: $FILE")
PYEOF

git add "$FILE"
git commit -m "lesson-close: $DATE" -- "$FILE"

if [[ "$NO_PUSH" != "--no-push" ]]; then
  git push
fi

echo "Lesson closed: $FILE"

#!/bin/bash
# frontmatter.sh — shared YAML frontmatter field reader
# Extracted from scripts/memory-validate.sh (issue #229) so update.sh's
# repair_pass() can check owner:/horizon: without duplicating the awk.
# Usage: source "$SCRIPT_DIR/.claude/lib/frontmatter.sh"

[ -n "${_IWE_FRONTMATTER_SOURCED:-}" ] && return 0
_IWE_FRONTMATTER_SOURCED=1

# get_field <file> <field> — print the value of a top-level frontmatter field.
# Strips surrounding quotes and leading/trailing whitespace (incl. CR, so
# CRLF-saved files don't break exact-match callers like update.sh's owner:user
# guard — issue #229 review). Empty output if the file has no frontmatter,
# the field is absent, or f is not exactly 1 (field must be inside the FIRST
# --- ... --- block).
#
# issue #281: Claude Code's native auto-memory writes type/horizon/domains/
# status/valid_from/owner/schema_version NESTED under a `metadata:` key
# instead of top-level — a second, independently-evolving frontmatter dialect
# next to the flat one this reader was built for (issue #229/#217). Top-level
# match still wins when present (existing flat files keep working unchanged);
# only when no top-level match is found do we look inside `metadata:` (first
# line at column 0 that isn't blank closes the block). Does not parse
# multi-line YAML lists (`domains:` as `- item` lines) — same pre-existing
# limitation as the flat-field case; only extends WHERE the field is found.
get_field() {
    local file="$1" field="$2"
    awk '
        /^---/{f++; next}
        f!=1{next}
        /^'"$field"':/{gsub(/^[^:]+: */,""); gsub(/["'"'"']/,""); gsub(/^[ \t]+|[ \t\r]+$/,""); print; exit}
        /^metadata:[ \t\r]*$/{in_meta=1; next}
        in_meta && /^[^ \t]/{in_meta=0}
        in_meta && /^[ \t]+'"$field"':/{gsub(/^[ \t]*[^:]+: */,""); gsub(/["'"'"']/,""); gsub(/^[ \t]+|[ \t\r]+$/,""); print; exit}
    ' "$file"
}

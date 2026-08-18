#!/usr/bin/env python3
"""settings-merge-preview.py — key-level 3-way-style merge PREVIEW for settings.json.

WP-7 F71 stage A (peer-session 2026-08-14-05): observability only. Writes the
merged result to a separate preview file and reports what would change; the
real settings.json is never touched here (auto-apply is a separate, flag-gated
stage B).

Usage:
    settings-merge-preview.py <template_settings> <workspace_settings> <preview_out>

Merge rules (peer-session 2026-08-14-03 consensus):
    hooks.*                    union per event; entry identity = canonical JSON;
                               user entries first, template-new appended
    permissions.allow/deny,
    permissions.additionalDirectories
                               list union, user entries first
    any other key              template-only -> added; user-only -> kept;
                               both differ -> user value kept, key reported
                               as a conflict

Stdout: one JSON object with counters and conflict keys (machine-readable,
update.sh renders it for the pilot). Exit 0 = preview written; 1 = invalid
input, nothing written.
"""

import json
import os
import sys
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def union_list(user_items, template_items):
    """User items first, then template items not already present (by canonical form)."""
    seen = {canonical(item) for item in user_items}
    added = [item for item in template_items if canonical(item) not in seen]
    deduped = len(template_items) - len(added)
    return user_items + added, len(added), deduped


def merge_hooks(user_hooks, template_hooks, report):
    merged = dict(user_hooks)
    for event, template_entries in template_hooks.items():
        if not isinstance(template_entries, list):
            merged.setdefault(event, template_entries)
            continue
        user_entries = merged.get(event, [])
        if not isinstance(user_entries, list):
            report["conflicts"].append(f"hooks.{event}")
            continue
        merged[event], added, deduped = union_list(user_entries, template_entries)
        report["hooks_added_from_template"] += added
        report["hooks_deduped"] += deduped
    return merged


def merge_permissions(user_perms, template_perms, report):
    merged = dict(user_perms)
    for key, template_value in template_perms.items():
        user_value = merged.get(key)
        if isinstance(template_value, list) and isinstance(user_value, list):
            merged[key], added, _ = union_list(user_value, template_value)
            report["permissions_added_from_template"] += added
        elif key not in merged:
            merged[key] = template_value
            report["keys_added_from_template"] += 1
        elif canonical(user_value) != canonical(template_value):
            report["conflicts"].append(f"permissions.{key}")
    return merged


def merge_settings(template, workspace, report):
    merged = dict(workspace)
    for key, template_value in template.items():
        if key == "hooks" and isinstance(template_value, dict):
            user_value = merged.get("hooks", {})
            if isinstance(user_value, dict):
                merged["hooks"] = merge_hooks(user_value, template_value, report)
            else:
                report["conflicts"].append("hooks")
            continue
        if key == "permissions" and isinstance(template_value, dict):
            user_value = merged.get("permissions", {})
            if isinstance(user_value, dict):
                merged["permissions"] = merge_permissions(user_value, template_value, report)
            else:
                report["conflicts"].append("permissions")
            continue
        if key not in merged:
            merged[key] = template_value
            report["keys_added_from_template"] += 1
        elif canonical(merged[key]) != canonical(template_value):
            report["conflicts"].append(key)
    report["keys_kept_user_only"] = sum(1 for key in workspace if key not in template)
    return merged


def main(argv):
    if len(argv) != 4:
        print("usage: settings-merge-preview.py <template_settings> <workspace_settings> <preview_out>", file=sys.stderr)
        return 1

    template_path, workspace_path, preview_path = argv[1], argv[2], argv[3]
    try:
        with open(template_path, encoding="utf-8") as handle:
            template = json.load(handle)
        with open(workspace_path, encoding="utf-8") as handle:
            workspace = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"settings-merge-preview: invalid input: {exc}", file=sys.stderr)
        return 1
    if not isinstance(template, dict) or not isinstance(workspace, dict):
        print("settings-merge-preview: both inputs must be JSON objects", file=sys.stderr)
        return 1

    report = {
        "keys_added_from_template": 0,
        "keys_kept_user_only": 0,
        "hooks_added_from_template": 0,
        "hooks_deduped": 0,
        "permissions_added_from_template": 0,
        "conflicts": [],
    }
    merged = merge_settings(template, workspace, report)

    # Atomic write: a torn preview file must never exist (mkstemp + os.replace).
    out_dir = os.path.dirname(os.path.abspath(preview_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=".settings-preview-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, preview_path)
    except OSError as exc:
        os.unlink(tmp_path)
        print(f"settings-merge-preview: cannot write preview: {exc}", file=sys.stderr)
        return 1

    report["preview"] = preview_path
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

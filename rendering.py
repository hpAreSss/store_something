"""Template-rendering helpers for JSM field values."""


class _SafeDict(dict):
    """Missing keys render as empty strings (used for per-issue rendering)."""

    def __missing__(self, key):
        return ""


class _PartialDict(dict):
    """Missing keys are left untouched as `{key}` (used for the extras pass)."""

    def __missing__(self, key):
        return "{" + key + "}"


def render_extras(value, extras: dict):
    """Substitute CLI-provided `{placeholders}` in a string; leave unknowns alone.

    Non-string values pass through unchanged.
    """
    if not isinstance(value, str) or not extras:
        return value
    return value.format_map(_PartialDict(extras))


def aggregate_field(issues, template: str, separator: str) -> str:
    """Render `template` for every Jira issue and join them with `separator`.

    Template placeholders: `{key}` plus any Jira field name present in
    `issue.fields` (including custom fields such as `customfield_10010`).
    Missing placeholders render as empty strings.
    """
    rendered = []
    for info in issues:
        ctx = {"key": info.key}
        ctx.update(info.fields)
        rendered.append(template.format_map(_SafeDict(ctx)))
    return separator.join(rendered)


def build_jsm_fields(template: dict, issues, tag: str, extras: dict) -> dict:
    """Merge static `jsm_fields` from a template with its aggregated values."""
    jsm_fields = {}
    for name, value in (template.get("jsm_fields") or {}).items():
        jsm_fields[name] = render_extras(value, extras)
    if not any(k.lower() == "summary" for k in jsm_fields):
        jsm_fields["summary"] = f"Release for {tag}"

    aggregations = template.get("jsm_field_aggregations", {}) or {}
    for field_name, rule in aggregations.items():
        tmpl = render_extras(rule.get("template", "{key}"), extras)
        separator = render_extras(rule.get("separator", "\n"), extras)
        value = aggregate_field(issues, tmpl, separator)
        existing = jsm_fields.get(field_name)
        if existing:
            jsm_fields[field_name] = f"{existing}\n\n{value}".strip()
        else:
            jsm_fields[field_name] = value
    return jsm_fields

"""Interactive builder for a JSM-fields YAML snippet.

Uses the main config's `jira_fields` list to populate the per-issue placeholders
available for aggregated fields, and (optionally) JSM field metadata fetched
from the service desk to show field names, required flags, default values,
and the allowed values for restricted fields (including cascading selects).
"""

import yaml

from logger import get_logger

log = get_logger(__name__)


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or (default or "")


def _ask_choice(prompt: str, choices: list[str]) -> str:
    joined = "/".join(choices)
    while True:
        val = input(f"{prompt} ({joined}): ").strip().lower()
        if val in choices:
            return val
        print(f"  please pick one of: {joined}")


def _format_default(defaults: list[dict]) -> str:
    if not defaults:
        return ""
    parts = [d.get("label") or d.get("value") or "?" for d in defaults]
    return f"  [default: {', '.join(parts)}]"


def _print_jsm_fields_overview(jsm_field_meta: list[dict]) -> None:
    print("\nJSM fields available on this request type:")
    for f in jsm_field_meta:
        mark = "*" if f["required"] else " "
        extra = ""
        if f["valid_values"]:
            labels = [v["label"] for v in f["valid_values"] if v.get("label")]
            if f["schema_type"] == "option-with-child":
                extra = f"  [cascading; top-level: {', '.join(labels)}]"
            else:
                extra = f"  [allowed: {', '.join(labels)}]"
        extra += _format_default(f.get("default_values") or [])
        print(f"  {mark} {f['id']}  ({f['name']}){extra}")
    print("  (* = required; fields with defaults are auto-filled by JSM if omitted)\n")


def _pick_from_options(options: list[dict], level_label: str) -> dict | None:
    """Interactively pick one option from a list. Returns the chosen option
    dict or None if the user aborts with a blank input."""
    print(f"  {level_label} options:")
    for i, v in enumerate(options, 1):
        marker = " (has children)" if v.get("children") else ""
        print(f"    {i}) {v.get('label')}  (value={v.get('value')}){marker}")
    while True:
        raw = input(
            f"  pick {level_label} number, or type value/label "
            "(blank to abort): "
        ).strip()
        if not raw:
            return None
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
            print("  out of range")
            continue
        for v in options:
            if raw in (v.get("value"), v.get("label")):
                return v
        print("  not in allowed list; try again")


def _pick_cascading_value(valid_values: list[dict]):
    """Prompt for parent option, then (if it has children) prompt for a child.

    Returns either a plain string (parent value, no child picked) or a dict
    shaped like `{"value": parent, "child": {"value": child}}` which is what
    JSM expects for cascading selects on create.
    """
    parent = _pick_from_options(valid_values, "parent")
    if not parent:
        return None
    parent_val = parent.get("value") or parent.get("label")
    children = parent.get("children") or []
    if not children:
        return parent_val
    print("  (this option has sub-options; press blank to leave child unset)")
    child = _pick_from_options(children, "child")
    if not child:
        return parent_val
    child_val = child.get("value") or child.get("label")
    return {"value": parent_val, "child": {"value": child_val}}


def _pick_valid_value(valid_values: list[dict]) -> str:
    chosen = _pick_from_options(valid_values, "value")
    if not chosen:
        return ""
    return chosen.get("value") or chosen.get("label") or ""


def build_template(cfg: dict, jsm_field_meta: list[dict] | None = None) -> dict:
    jira_fields = list(cfg.get("jira_fields") or [])
    placeholders = ["key"] + jira_fields

    print("\n=== JSM Template Builder ===")
    if jira_fields:
        print("Jira fields usable as per-issue placeholders:")
        for ph in placeholders:
            print(f"  {{{ph}}}")
    else:
        print("(config has no jira_fields — only {key} is available)")

    lookup: dict[str, dict] = {}
    for f in jsm_field_meta or []:
        if f.get("id"):
            lookup[f["id"].lower()] = f
        if f.get("name"):
            lookup.setdefault(f["name"].lower(), f)
    if lookup:
        _print_jsm_fields_overview(jsm_field_meta)
        print(
            "Tip: fields with a [default: ...] value will be auto-filled by JSM\n"
            "     if you omit them. Fields filled by server-side automation\n"
            "     rules are not exposed by the API — leave them out.\n"
        )
    else:
        print("(no JSM field metadata available; values are not validated)\n")

    print("Enter each JSM field you want to configure. Blank name finishes.\n")

    jsm_fields: dict = {}
    jsm_field_aggregations: dict = {}

    while True:
        name = _ask("JSM field name or id (e.g. 'Priority' or 'customfield_20001')")
        if not name:
            break
        if name in jsm_fields or name in jsm_field_aggregations:
            print(f"  {name!r} already configured — overwriting")
            jsm_fields.pop(name, None)
            jsm_field_aggregations.pop(name, None)

        meta = lookup.get(name.lower())
        if lookup and not meta:
            print(f"  warning: {name!r} is not in the request type's field list")

        cascading = bool(meta and meta.get("schema_type") == "option-with-child")
        restricted = bool(meta and meta.get("valid_values")) and not cascading

        if cascading:
            print(f"  ({name!r} is a cascading select)")
        elif restricted:
            print(f"  ({name!r} has a fixed set of allowed values)")

        kind = _ask_choice("  type", ["static", "aggregate"])

        if kind == "static":
            if cascading:
                val = _pick_cascading_value(meta["valid_values"])
                if val is None:
                    print("  aborted; skipping field")
                    continue
            elif restricted:
                val = _pick_valid_value(meta["valid_values"])
                if not val:
                    print("  aborted; skipping field")
                    continue
            else:
                val = _ask(
                    "  value ({placeholders} filled from --set KEY=VALUE; "
                    "unresolved ones stay as-is)"
                )
            jsm_fields[name] = val
        else:
            if cascading or restricted:
                print(
                    "  warning: this field only accepts specific values; the "
                    "aggregated string is unlikely to match unless the template "
                    "resolves to exactly one allowed value."
                )
            print("  available per-issue placeholders:")
            for ph in placeholders:
                print(f"    {{{ph}}}")
            template = _ask("  template")
            separator = _ask("  separator", default="\\n")
            separator = separator.encode("utf-8").decode("unicode_escape")
            jsm_field_aggregations[name] = {
                "template": template,
                "separator": separator,
            }
        print()

    result: dict = {}
    if jsm_fields:
        result["jsm_fields"] = jsm_fields
    if jsm_field_aggregations:
        result["jsm_field_aggregations"] = jsm_field_aggregations
    return result


def write_template(template: dict, output_path: str | None) -> None:
    text = yaml.safe_dump(template, sort_keys=False, allow_unicode=True)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        log.info("Template written to %s", output_path)
        print(f"Template written to {output_path}")
    else:
        print("\n--- generated template ---")
        print(text)

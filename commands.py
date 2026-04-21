"""Implementations of the CLI subcommands and their config helpers."""

import tempfile

import yaml

from git_client import GitRepoClient
from jira_client import JiraClient
from jsm_client import JsmClient
from logger import get_logger
from rendering import build_jsm_fields
from template_builder import build_template, write_template
from validation import validate_attachments

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Config access
# ---------------------------------------------------------------------------
def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def templates(cfg: dict) -> dict:
    return cfg.get("templates") or {}


def get_template(cfg: dict, name: str) -> dict:
    all_templates = templates(cfg)
    if name not in all_templates:
        available = ", ".join(sorted(all_templates)) or "(none defined)"
        raise SystemExit(
            f"Template {name!r} not found in config. Available: {available}"
        )
    tpl = all_templates[name] or {}
    for required in ("service_desk_id", "request_type_id"):
        if required not in tpl:
            raise SystemExit(
                f"Template {name!r} is missing required key {required!r}"
            )
    return tpl


def build_jsm_client(cfg: dict, template: dict) -> JsmClient:
    jsm_cfg = cfg["jsm"]
    return JsmClient(
        url=jsm_cfg["url"],
        username=jsm_cfg["username"],
        api_token=jsm_cfg["api_token"],
        service_desk_id=str(template["service_desk_id"]),
        request_type_id=str(template["request_type_id"]),
    )


def describe_jsm_fields(cfg: dict, template: dict) -> list[dict] | None:
    """Fetch JSM field metadata for a template; return None on failure."""
    jsm_cfg = cfg.get("jsm") or {}
    for k in ("url", "username", "api_token"):
        if k not in jsm_cfg:
            log.info("JSM connection incomplete; skipping field-metadata fetch")
            return None
    try:
        return build_jsm_client(cfg, template).describe_fields()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not fetch JSM field metadata: %s", exc)
        return None


# ---------------------------------------------------------------------------
# list-templates
# ---------------------------------------------------------------------------
def list_templates(cfg: dict) -> int:
    names = sorted(templates(cfg))
    if not names:
        print("No templates defined.")
        return 0
    print("Templates:")
    for n in names:
        tpl = cfg["templates"][n] or {}
        sd = tpl.get("service_desk_id", "?")
        rt = tpl.get("request_type_id", "?")
        print(f"  - {n}  (service_desk_id={sd}, request_type_id={rt})")
    return 0


# ---------------------------------------------------------------------------
# create-template
# ---------------------------------------------------------------------------
def create_template_cmd(args, cfg: dict) -> int:
    stub_template = {
        "service_desk_id": args.service_desk_id,
        "request_type_id": args.request_type_id,
    }
    jsm_meta = describe_jsm_fields(cfg, stub_template)
    tpl_body = build_template(cfg, jsm_field_meta=jsm_meta)
    tpl_body = {
        "service_desk_id": args.service_desk_id,
        "request_type_id": args.request_type_id,
        **tpl_body,
    }
    wrapped = {"templates": {args.template: tpl_body}}
    write_template(wrapped, getattr(args, "output", None))
    return 0


# ---------------------------------------------------------------------------
# create-request
# ---------------------------------------------------------------------------
def create_request(args, cfg: dict) -> int:
    template = get_template(cfg, args.template)

    git_client = GitRepoClient(cfg.get("repo_path", "."))
    if git_client.has_tag("latest"):
        log.info("Tag 'latest' found; collecting commits latest..%s", args.tag)
        from_ref = "latest"
    else:
        log.info("Tag 'latest' not found; collecting all commits reachable from %s", args.tag)
        from_ref = None
    jira_keys = git_client.jira_keys_between(from_ref, args.tag)

    jira_cfg = cfg["jira"]
    jira_client = JiraClient(
        url=jira_cfg["url"],
        username=jira_cfg["username"],
        api_token=jira_cfg["api_token"],
    )

    jira_fields = cfg.get("jira_fields", ["Summary"])
    resolved_fields = jira_client.resolve_field_names(jira_fields)
    log.info(
        "Resolved Jira fields: %s",
        ", ".join(f"{n}->{i}" for n, i in resolved_fields),
    )

    with tempfile.TemporaryDirectory(prefix="jira_att_") as tmpdir:
        issues = []
        for key in jira_keys:
            info = jira_client.fetch_issue(
                key,
                resolved_fields=resolved_fields,
                download_dir=tmpdir,
                download_attachments=True,
            )
            if info:
                issues.append(info)

        violations = validate_attachments(issues)
        if violations:
            log.error("Attachment validation failed:")
            for msg in violations:
                log.error("  %s", msg)
            print("Attachment validation failed for the following Jira issues:")
            for msg in violations:
                print(f"  - {msg}")
            return 2

        jsm_fields = build_jsm_fields(template, issues, args.tag, args.extras)

        jsm_client = build_jsm_client(cfg, template)
        jsm_fields = jsm_client.resolve_field_keys(jsm_fields)
        response = jsm_client.create_request(jsm_fields)
        issue_key = response.get("issueKey") or response.get("key")
        log.info("JSM request (%s) created: %s", args.template, issue_key)

        if issue_key:
            all_files = [att["local_path"] for info in issues for att in info.attachments]
            if all_files:
                jsm_client.attach_files(issue_key, all_files)

    print(f"Created JSM request: {issue_key}")
    return 0

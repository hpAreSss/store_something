"""Entry point: parse arguments and dispatch to the matching subcommand."""

import argparse
import sys

from commands import (
    create_request,
    create_template_cmd,
    list_templates,
    load_config,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_req = sub.add_parser(
        "create-request",
        help="Create a JSM ticket from git + Jira data using a named template",
    )
    p_req.add_argument("--config", required=True, help="Path to YAML config")
    p_req.add_argument(
        "--template",
        required=True,
        help="Name of the template under `templates:` in the config",
    )
    p_req.add_argument(
        "--tag",
        required=True,
        help="Target git tag/ref (range is: latest..<tag> if 'latest' exists)",
    )
    p_req.add_argument(
        "--set",
        dest="set_pairs",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Extra key=value pair used to render {placeholders} inside the "
            "template's jsm_fields and jsm_field_aggregations. Repeatable."
        ),
    )

    p_tpl = sub.add_parser(
        "create-template",
        help="Interactively build a named template",
    )
    p_tpl.add_argument("--config", required=True, help="Path to YAML config")
    p_tpl.add_argument(
        "--template",
        required=True,
        help="Name under which the generated template will be emitted",
    )
    p_tpl.add_argument(
        "--service-desk-id",
        required=True,
        help="JSM service desk id for this template",
    )
    p_tpl.add_argument(
        "--request-type-id",
        required=True,
        help="JSM request type id for this template",
    )
    p_tpl.add_argument(
        "--output",
        help="Write the generated YAML to this path (otherwise prints to stdout)",
    )

    p_list = sub.add_parser(
        "list-templates",
        help="List template names defined in the config",
    )
    p_list.add_argument("--config", required=True, help="Path to YAML config")

    args = parser.parse_args()
    args.extras = _pairs_to_dict(getattr(args, "set_pairs", []))
    return args


def _pairs_to_dict(pairs: list[str]) -> dict:
    extras: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--set expects KEY=VALUE, got: {pair!r}")
        key, val = pair.split("=", 1)
        extras[key] = val
    return extras


def run(args):
    cfg = load_config(args.config)
    if args.command == "list-templates":
        return list_templates(cfg)
    if args.command == "create-template":
        return create_template_cmd(args, cfg)
    return create_request(args, cfg)


def entrypoint():
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(entrypoint())

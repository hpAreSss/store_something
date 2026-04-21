"""Runtime checks applied before a JSM request is created."""


def validate_attachments(issues) -> list[str]:
    """Ensure each issue has >=1 "testing*" and <=1 "execute*" attachment.

    Returns a list of human-readable violation messages. An empty list means
    all issues are valid. Prefix match is case-insensitive.
    """
    violations: list[str] = []
    for info in issues:
        names = [att["filename"] for att in info.attachments]
        testing = [n for n in names if n.lower().startswith("testing")]
        execute = [n for n in names if n.lower().startswith("execute")]
        if not testing:
            violations.append(
                f"{info.key}: missing attachment starting with 'testing'"
            )
        if len(execute) > 1:
            violations.append(
                f"{info.key}: {len(execute)} attachments starting with 'execute' "
                f"(max 1 allowed): {execute}"
            )
    return violations

"""Client for the Jira instance — fetches configurable fields + attachments."""

import os
from typing import Iterable

from atlassian import Jira

from logger import get_logger
from models import JiraIssueInfo

log = get_logger(__name__)


def _normalize(value):
    """Collapse common Jira field shapes into a human-readable string.

    Jira returns complex values for many built-in fields (status, priority,
    user, etc.) and for some custom fields. Config templates normally want a
    plain string, so we extract the most useful scalar.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("displayName", "name", "value", "key"):
            if key in value and isinstance(value[key], (str, int, float)):
                return str(value[key])
        return str(value)
    if isinstance(value, list):
        return ", ".join(_normalize(v) for v in value)
    return str(value)


class JiraClient:
    def __init__(self, url: str, username: str, api_token: str):
        self._client = Jira(url=url, username=username, password=api_token)
        self._field_index: dict[str, str] | None = None

    def _load_field_index(self) -> dict[str, str]:
        """Lazy-load and cache a lowercase-name/lowercase-id → field id map."""
        if self._field_index is None:
            all_fields = self._client.get_all_fields()
            index: dict[str, str] = {}
            collisions: dict[str, list[str]] = {}
            for f in all_fields:
                fid = f.get("id")
                fname = f.get("name") or ""
                if not fid:
                    continue
                index[fid.lower()] = fid
                key = fname.lower()
                if key and key not in index:
                    index[key] = fid
                elif key and index.get(key) != fid:
                    collisions.setdefault(key, [index[key]]).append(fid)
            for name, ids in collisions.items():
                log.warning(
                    "Jira field name %r is ambiguous, multiple ids %s; using %r",
                    name, ids, index[name],
                )
            self._field_index = index
            log.info("Loaded %d Jira field definitions", len(all_fields))
        return self._field_index

    def resolve_field_names(self, names: Iterable[str]) -> list[tuple[str, str]]:
        """Map user-supplied field names (or ids) to Jira field ids.

        Returns a list of `(user_label, field_id)` pairs, preserving the
        original user spelling so it can later be used as a template
        placeholder. Raises `KeyError` for unknown names.
        """
        index = self._load_field_index()
        resolved: list[tuple[str, str]] = []
        for name in names:
            fid = index.get(name.lower())
            if not fid:
                raise KeyError(f"Unknown Jira field: {name!r}")
            resolved.append((name, fid))
        return resolved

    def fetch_issue(
        self,
        key: str,
        resolved_fields: list[tuple[str, str]],
        download_dir: str | None = None,
        download_attachments: bool = False,
    ) -> JiraIssueInfo | None:
        """Fetch the given fields for a Jira issue.

        `resolved_fields` is a list of `(user_label, field_id)` pairs as
        produced by `resolve_field_names()`. Values in the returned
        `JiraIssueInfo.fields` are keyed by `user_label`, so templates can
        reference fields by name.
        """
        ids = [fid for _, fid in resolved_fields]
        fetch_list = list(ids)
        if download_attachments and "attachment" not in fetch_list:
            fetch_list.append("attachment")

        try:
            issue = self._client.issue(key, fields=",".join(fetch_list))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not fetch %s: %s", key, exc)
            return None

        raw_fields = issue.get("fields", {}) or {}
        info = JiraIssueInfo(key=key)
        for user_label, fid in resolved_fields:
            info.fields[user_label] = _normalize(raw_fields.get(fid))

        if download_attachments:
            self._collect_attachments(key, raw_fields, info, download_dir)
        return info

    def _collect_attachments(self, key, raw_fields, info, download_dir):
        if not download_dir:
            return
        for att in raw_fields.get("attachment", []) or []:
            filename = att.get("filename")
            content_url = att.get("content")
            if not filename or not content_url:
                continue
            local_path = os.path.join(download_dir, f"{key}_{filename}")
            try:
                self._download_attachment(content_url, local_path)
                info.attachments.append(
                    {
                        "filename": filename,
                        "content_url": content_url,
                        "local_path": local_path,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Attachment %s for %s skipped: %s", filename, key, exc)

    def _download_attachment(self, url: str, dest: str) -> None:
        resp = self._client._session.get(url, stream=True)
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

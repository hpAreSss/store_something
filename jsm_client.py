"""Client for the JSM instance — creates customer requests + attachments."""

import os
from typing import Iterable

from atlassian import ServiceDesk

from logger import get_logger

log = get_logger(__name__)


def _normalize_options(options: list) -> list[dict]:
    """Recursively flatten a `validValues` tree, preserving children."""
    result: list[dict] = []
    for o in options or []:
        result.append(
            {
                "value": o.get("value"),
                "label": o.get("label"),
                "children": _normalize_options(o.get("children") or []),
            }
        )
    return result


class JsmClient:
    def __init__(
        self,
        url: str,
        username: str,
        api_token: str,
        service_desk_id: str,
        request_type_id: str,
    ):
        self._client = ServiceDesk(
            url=url, username=username, password=api_token
        )
        self.service_desk_id = service_desk_id
        self.request_type_id = request_type_id
        self._fields_cache: list[dict] | None = None
        self._field_index: dict[str, str] | None = None

    def describe_fields(self) -> list[dict]:
        """Return (and cache) field metadata for this request type.

        Each entry:
            {"id", "name", "required", "schema_type",
             "valid_values": [ {value, label, children: [...]} ],
             "default_values": [ {value, label} ]}
        Cascading selects preserve their full parent/child hierarchy in
        `valid_values[*].children`.
        """
        if self._fields_cache is not None:
            return self._fields_cache
        raw = self._client.get_request_type_fields(
            service_desk_id=self.service_desk_id,
            request_type_id=self.request_type_id,
        )
        out: list[dict] = []
        for f in raw.get("requestTypeFields", []) or []:
            schema_type = (f.get("jiraSchema") or {}).get("type", "")
            out.append(
                {
                    "id": f.get("fieldId"),
                    "name": f.get("name"),
                    "required": bool(f.get("required")),
                    "schema_type": schema_type,
                    "valid_values": _normalize_options(f.get("validValues") or []),
                    "default_values": [
                        {"value": d.get("value"), "label": d.get("label")}
                        for d in (f.get("defaultValues") or [])
                    ],
                }
            )
        self._fields_cache = out
        return out

    def _load_field_index(self) -> dict[str, str]:
        """Lowercase-name/lowercase-id → field id, built lazily from cache."""
        if self._field_index is not None:
            return self._field_index
        index: dict[str, str] = {}
        collisions: dict[str, list[str]] = {}
        for f in self.describe_fields():
            fid = f.get("id")
            fname = (f.get("name") or "").lower()
            if not fid:
                continue
            index[fid.lower()] = fid
            if fname and fname not in index:
                index[fname] = fid
            elif fname and index.get(fname) != fid:
                collisions.setdefault(fname, [index[fname]]).append(fid)
        for name, ids in collisions.items():
            log.warning(
                "JSM field name %r is ambiguous, multiple ids %s; using %r",
                name, ids, index[name],
            )
        self._field_index = index
        return index

    def resolve_field_id(self, name: str) -> str:
        """Map a user-supplied field name or id to its JSM field id."""
        index = self._load_field_index()
        fid = index.get(name.lower())
        if not fid:
            raise KeyError(f"Unknown JSM field: {name!r}")
        return fid

    def resolve_field_keys(self, fields: dict) -> dict:
        """Return a new dict with every key replaced by its resolved field id."""
        out: dict = {}
        for name, value in fields.items():
            out[self.resolve_field_id(name)] = value
        return out

    def create_request(self, fields: dict) -> dict:
        log.info("Creating JSM request on service desk %s", self.service_desk_id)
        return self._client.create_customer_request(
            service_desk_id=self.service_desk_id,
            request_type_id=self.request_type_id,
            values_dict=fields,
        )

    def attach_files(self, issue_key: str, file_paths: Iterable[str]) -> None:
        for path in file_paths:
            if not os.path.isfile(path):
                continue
            try:
                temp = self._client.attach_temporary_file(
                    service_desk_id=self.service_desk_id, filename=path
                )
                temp_id = temp["temporaryAttachments"][0]["temporaryAttachmentId"]
                self._client.create_attachment(
                    issue_id_or_key=issue_key,
                    temp_attachment_id=temp_id,
                    public=True,
                )
                log.info("Attached %s to %s", os.path.basename(path), issue_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not attach %s: %s", path, exc)

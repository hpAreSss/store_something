"""Git repository helper — extracts Jira keys from commit messages."""

import re

from git import Repo

from logger import get_logger

log = get_logger(__name__)

JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


class GitRepoClient:
    def __init__(self, repo_path: str):
        self.repo = Repo(repo_path, search_parent_directories=True)
        if self.repo.bare:
            raise ValueError(f"Repository at {repo_path} is bare")

    def has_tag(self, name: str) -> bool:
        """Return True if a tag with the exact given name exists."""
        return any(tag.name == name for tag in self.repo.tags)

    def commits_between(self, from_ref: str | None, to_ref: str) -> list:
        """Commits reachable from `to_ref`.

        If `from_ref` is given, returns `from_ref..to_ref`; otherwise returns
        every commit reachable from `to_ref`.
        """
        if from_ref:
            rev = f"{from_ref}..{to_ref}"
        else:
            rev = to_ref
        log.info("Collecting commits for rev spec %s", rev)
        return list(self.repo.iter_commits(rev))

    def jira_keys_between(self, from_ref: str | None, to_ref: str) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for commit in self.commits_between(from_ref, to_ref):
            first_line = commit.message.splitlines()[0] if commit.message else ""
            m = JIRA_KEY_RE.match(first_line.strip())
            if not m:
                continue
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                keys.append(key)
        log.info("Found %d unique Jira keys", len(keys))
        return keys

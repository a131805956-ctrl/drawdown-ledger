from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[3]
PRIVATE_DIRECTORY_PREFIXES = (
    ".superpowers/",
    ".worktrees/",
    ".runtime/",
    "data/",
    "reports/private/",
)
PRIVATE_MARKET_CACHE_SUFFIXES = (".parquet", ".sqlite", ".sqlite3", ".db")


def test_git_tracked_paths_exclude_private_boundaries() -> None:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_paths = tuple(path for path in result.stdout.split("\0") if path)

    private_paths = [
        path
        for path in tracked_paths
        if path.startswith(PRIVATE_DIRECTORY_PREFIXES)
        or path.lower().endswith(PRIVATE_MARKET_CACHE_SUFFIXES)
    ]

    assert not private_paths, f"Private paths must not be tracked: {private_paths}"

"""Path rules shared by the contract validator and the drift checker."""
import fnmatch

# Never editable by an agent-authored change, whatever the contract says.
PROTECTED_PATHS = [".gitlab-ci.yml", ".gitlab/", "ci/"]

WILDCARD_CHARS = "*?["


def path_matches(path: str, pattern: str) -> bool:
    """True if `path` falls under `pattern` (exact, glob, or dir prefix)."""
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or fnmatch.fnmatch(path, pattern)


def matches_any(path: str, patterns) -> bool:
    return any(path_matches(path, p) for p in patterns)


def overlaps_protected(pattern: str) -> bool:
    """True if an allowed-path pattern could cover a protected path."""
    for prot in PROTECTED_PATHS:
        if prot.endswith("/"):
            if pattern.startswith(prot) or fnmatch.fnmatch(prot, pattern):
                return True
        elif path_matches(prot, pattern):
            return True
    return False

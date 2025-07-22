"""
json_pointer.py - rewrite raw-GitHub URIs inside JSON structures
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex matching the four groups of ``raw.githubusercontent.com`` URI up to and including the
# branch / tag segment we want to swap.
RAW_GITHUB_RE = re.compile(
    r"https://raw\.githubusercontent\.com/"
    r"(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+)/"
    r"(?:refs/(?:heads|tags|remotes/[^/]+)/)?"   # optional, non-capturing
    r"(?P<branch>[^/]+)/"
)

# Keys that are typically URIs inside our JSON Schemas / metadata instances.
#   e.g., "$id": "https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/FEGA.biomaterial.json"
ID_KEYS = {"$id", "$ref", "@context"}

_ALLOWED_SEGMENTS = {"owner", "repo", "branch"}

# -------
# Validation of input helper
# -------

def _validate_replacements(replacements: Dict[str, Tuple[str, str]]) -> None:
    """Ensure *replacements* is well-formed.

    * keys must be a subset of {owner, repo, branch}
    * each value must be a 2-tuple of strings (source, target)
    """
    if not isinstance(replacements, dict):
        raise TypeError("replacements must be a dict with the format of: {segment: (source, target)}")

    for seg, tpl in replacements.items():
        if seg not in _ALLOWED_SEGMENTS:
            raise ValueError(f"Invalid segment '{seg}'. Allowed: {sorted(_ALLOWED_SEGMENTS)}")
        if (
            not isinstance(tpl, tuple)
            or len(tpl) != 2
            or not all(isinstance(x, str) for x in tpl)
        ):
            raise ValueError(
                f"Value for '{seg}' must be a tuple of two strings (source, target). Instead, '{tpl}' was given."
            )

# -------
# Low-level URI helpers
# -------

def _swap_multiple_segments(
    uri: str,
    replacements: Dict[str, Tuple[str, str]],
    require_all_match: bool = True,
) -> Optional[str]:
    """Return a modified URI or ``None`` when no replacement applies.

    Parameters
    ----------
    uri : str
        Raw GitHub URI to inspect.
    replacements : dict
        Mapping like ``{"owner": ("old", "new"), "repo": ("oldrepo", "newrepo"), "branch": ("oldbranch", "newbranch")}``.
        Not all groups are required to be given.
    require_all_match : bool
        If True, *all* specified segments must match their *source* before any
        replacement occurs. If False, each segment is replaced independently
        when its *source* matches.
    """
    match = RAW_GITHUB_RE.match(uri)
    if match is None:
        return None

    owner, repo, branch = (
        match.group("owner"),
        match.group("repo"),
        match.group("branch"),
    )

    if require_all_match:
        for group, (src, _tgt) in replacements.items():
            if match.group(group) != src:
                return None

    changed = False
    for group, (src, tgt) in replacements.items():
        current = match.group(group)
        if current == src:
            if group == "owner":
                owner = tgt
            elif group == "repo":
                repo = tgt
            elif group == "branch":
                branch = tgt
            changed = True

    if not changed:
        return None

    new_prefix = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    return RAW_GITHUB_RE.sub(new_prefix, uri, count=1)


# -------
# JSON tree traversal
# -------

def patch_json_tree(
    obj: Any,
    *,
    replacements: Dict[str, Tuple[str, str]],
    require_all_match: bool = True,
    uri_mappings: Optional[Dict[str, str]] = None,
) -> Any:
    """Traverse *obj* once, applying all requested URI replacements recursively to a given JSON."""
    _validate_replacements(replacements)

    if uri_mappings is None:
        uri_mappings = {}

    if isinstance(obj, dict):
        patched: Dict[str, Any] = {}
        for key, value in obj.items():
            if key in ID_KEYS and isinstance(value, str):
                patched[key] = _maybe_swap(value, replacements, require_all_match, uri_mappings)
            else:
                patched[key] = patch_json_tree(
                    value,
                    replacements=replacements,
                    require_all_match=require_all_match,
                    uri_mappings=uri_mappings,
                )
        return patched

    if isinstance(obj, list):
        return [
            patch_json_tree(
                item,
                replacements=replacements,
                require_all_match=require_all_match,
                uri_mappings=uri_mappings,
            )
            for item in obj
        ]

    # Anything other than lists or dictionaries (e.g., strings, numbers, booleans, None...) gets returned as it is, unchanged:
    return obj

# -------
# Internal helper
# -------

def _maybe_swap(
    value: Any,
    replacements: Dict[str, Tuple[str, str]],
    require_all_match: bool,
    uri_mappings: Dict[str, str],
):
    """
    Attempts to replace segments of a URI string based on provided replacements.
    Returns:
        Any: The swapped URI string if a replacement was made, otherwise the original value.
    """
    if not isinstance(value, str):
        return value

    new_uri = _swap_multiple_segments(value, replacements, require_all_match)
    if new_uri is None:
        return value

    uri_mappings.setdefault(value, new_uri)
    return new_uri

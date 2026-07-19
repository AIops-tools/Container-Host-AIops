"""Shared helpers for the container-host ops modules.

Docker Engine API list endpoints return a bare JSON array; inspect endpoints
return an object; a few management responses wrap items under a key. ``as_list``
normalises them. All host-returned text reaches the caller only after
``sanitize()`` (bounded length, output hygiene), applied via ``clean`` / ``clean_list``
at the read boundary.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from container_host_aiops.governance import opt_str, sanitize


def _seg(value: Any) -> str:
    """URL-encode one REST path segment.

    Agent-supplied identifiers (container/image/network ids, volume names,
    stack ids) are interpolated into URL paths; encoding with ``safe=""``
    ensures ``/``, ``..`` sequences, ``?`` etc. cannot rewrite the request path.
    """
    return quote(str(value), safe="")


_MAX_STR = 512
_MAX_DEPTH = 8


def as_list(data: Any, list_key: str | None = None) -> list[dict]:
    """Normalise a list payload to a list of dicts.

    A bare JSON array passes through; a dict is unwrapped via ``list_key`` when
    given, else returned as a single-item list when it looks like one record.
    """
    if isinstance(data, dict):
        items = data.get(list_key, []) if list_key else [data]
    else:
        items = data
    return [i for i in (items or []) if isinstance(i, dict)]


def clean(payload: Any) -> Any:
    """Return an injection-safe copy of a raw host payload."""
    return _sanitize_obj(payload)


def clean_list(data: Any, list_key: str | None = None) -> list[dict]:
    """as_list + recursive sanitize — the standard read-path normalisation."""
    return [_sanitize_obj(row) for row in as_list(data, list_key)]


def s(value: Any, limit: int = 128) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)


def opt(value: Any, limit: int = 128) -> str | None:
    """Sanitize an *optional* field, preserving the difference between absent and empty.

    Companion to :func:`s`, which folds ``None`` into ``""``. Docker omits keys
    it has nothing to say about (a created-but-never-started container has no
    ``Status``; a dangling image has no ``RepoTags``), and that is a different
    fact from the field being present and blank. Use this for anything optional;
    keep :func:`s` for values that always exist.
    """
    return opt_str(value, limit)


def short_id(cid: Any) -> str | None:
    """Docker's short 12-char id form for display, or None when there is no id.

    An id the Engine did not report comes back as ``None`` rather than ``""`` —
    an empty id string reads as a real (blank) identifier and a smaller model
    will happily quote it back as one.
    """
    if cid is None:
        return None
    return str(cid)[:12]


def container_name(container: dict) -> str | None:
    """Best-effort human name from a Docker container record.

    ``/containers/json`` gives ``Names: ["/foo"]``; ``inspect`` gives
    ``Name: "/foo"``. Both carry a leading slash Docker adds — strip it.
    """
    names = container.get("Names")
    if isinstance(names, list) and names:
        return str(names[0]).lstrip("/")
    name = container.get("Name")
    if name:
        return str(name).lstrip("/")
    return short_id(container.get("Id"))


def human_bytes(num: Any) -> str:
    """Format a byte count as a human-readable string (advisory display)."""
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} PiB"


def _sanitize_obj(obj: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_obj(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_obj(v, depth + 1) for v in obj]
    if isinstance(obj, str):
        return sanitize(obj, _MAX_STR)
    return obj

"""Image-scoped reads over the Docker Engine API (read-only).

These reads answer "what images are on the host, what does one look like inspected
(and its build history/layers), which images are dangling (untagged, safe-ish to
prune), and how much disk are images using". All host text is sanitized.
"""

from __future__ import annotations

from typing import Any

from container_host_aiops.ops._util import _seg, clean, clean_list, human_bytes, short_id

_MAX_ROWS = 500


def _strip_sha(image_id: object) -> object:
    """Drop Docker's ``sha256:`` prefix, leaving an absent id absent."""
    return None if image_id is None else str(image_id).removeprefix("sha256:")


def _num(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def list_images(conn: Any, all_images: bool = False) -> dict:
    """[READ] List images with tags, size, and dangling status.

    ``all_images`` includes intermediate layers; by default only top-level images.
    """
    rows = clean_list(
        conn.docker_get("/images/json", params={"all": "true" if all_images else "false"})
    )
    compact: list[dict] = []
    total_size = 0
    for r in rows:
        size = _num(r.get("Size"))
        total_size += size
        tags = r.get("RepoTags") or []
        compact.append({
            "id": short_id(_strip_sha(r.get("Id"))),
            "repoTags": tags,
            "sizeBytes": size,
            "sizeHuman": human_bytes(size),
            "dangling": _is_dangling(tags),
            "containers": r.get("Containers"),
        })
    compact.sort(key=lambda i: i["sizeBytes"], reverse=True)
    return {
        "total": len(rows),
        "totalSizeBytes": total_size,
        "totalSizeHuman": human_bytes(total_size),
        "images": compact[:_MAX_ROWS],
    }


def inspect_image(conn: Any, image_id: str) -> dict:
    """[READ] Inspect an image plus its build history (layers, sizes, commands)."""
    info = clean(conn.docker_get(f"/images/{_seg(image_id)}/json"))
    try:
        history = clean_list(conn.docker_get(f"/images/{_seg(image_id)}/history"))
    except Exception:  # noqa: BLE001 — history is advisory
        history = []
    layers = [
        {
            "createdBy": h.get("CreatedBy"),
            "sizeBytes": _num(h.get("Size")),
            "sizeHuman": human_bytes(_num(h.get("Size"))),
        }
        for h in history
    ]
    return {
        "id": short_id(_strip_sha(info.get("Id"))),
        "repoTags": info.get("RepoTags"),
        "sizeBytes": _num(info.get("Size")),
        "sizeHuman": human_bytes(_num(info.get("Size"))),
        "architecture": info.get("Architecture"),
        "os": info.get("Os"),
        "layerCount": len(layers),
        "history": layers[:_MAX_ROWS],
    }


def _unique_bytes(row: dict) -> int:
    """Bytes a prune would actually free: the image's own layers, not shared ones.

    ``Size`` counts every layer, including the base layers a still-tagged image
    holds too — pruning frees none of those. Measured on a real Docker 29.1.3: a
    dangling image reported ``Size 11.5 MB`` while only 3.4 MB was unique, and an
    earlier one promised 11.0 MiB and freed 1.6 KiB. A reclaim estimate that
    overstates by orders of magnitude is worse than none, because the whole point
    of the preview is deciding whether the prune is worth doing.

    ``SharedSize`` is only populated when the listing is asked for it, and is -1
    when unavailable — in which case fall back to ``Size`` rather than invent 0.

    It must be read from an **unfiltered** listing: Docker computes sharing
    against the images it returns, so a dangling-only listing reports
    ``SharedSize: 0`` for everything and the subtraction does nothing.
    """
    size = _num(row.get("Size"))
    shared = _num(row.get("SharedSize"))
    if shared is None or shared < 0:
        return size
    return max(0, size - shared)


def dangling_images(conn: Any) -> dict:
    """[READ] Untagged (dangling) images — the low-risk prune candidates."""
    # Unfiltered, so SharedSize is measured against every image; the dangling
    # filter is applied here instead.
    rows = [
        r
        for r in clean_list(
            conn.docker_get("/images/json", params={"shared-size": "true"})
        )
        if not [tag for tag in (r.get("RepoTags") or []) if tag != "<none>:<none>"]
    ]
    reclaimable = sum(_unique_bytes(r) for r in rows)
    return {
        "danglingCount": len(rows),
        "reclaimableBytes": reclaimable,
        "reclaimableHuman": human_bytes(reclaimable),
        # Docker's own unique-size accounting, which is an UPPER BOUND: layers
        # still held by containers or the build cache survive the prune, so the
        # exact figure is only knowable afterwards from SpaceReclaimed. Measured
        # on Docker 29.1.3: 3.4 MB unique, 1.6 KiB actually freed.
        "reclaimableIsUpperBound": True,
        "images": [
            {
                "id": short_id(_strip_sha(r.get("Id"))),
                "sizeBytes": _num(r.get("Size")),
                "sizeHuman": human_bytes(_num(r.get("Size"))),
                # What a prune actually frees, once shared layers are excluded.
                "reclaimableBytes": _unique_bytes(r),
            }
            for r in rows
        ][:_MAX_ROWS],
    }


def image_disk_usage(conn: Any) -> dict:
    """[READ] Image disk usage from ``/system/df`` (total, active, reclaimable)."""
    df = clean(conn.docker_get("/system/df"))
    images = df.get("Images") or []
    total = sum(_num(i.get("Size")) for i in images)
    shared = sum(_num(i.get("SharedSize")) for i in images)
    active = sum(1 for i in images if _num(i.get("Containers")) > 0)
    return {
        "imageCount": len(images),
        "activeCount": active,
        "totalSizeBytes": total,
        "totalSizeHuman": human_bytes(total),
        "sharedSizeBytes": shared,
        "reclaimableBytes": max(0, total - shared),
        "reclaimableHuman": human_bytes(max(0, total - shared)),
    }


def _is_dangling(tags: Any) -> bool:
    return not tags or tags == ["<none>:<none>"]

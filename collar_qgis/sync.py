"""Pure change tracking: local saves never imply a server write."""
import copy
import json
import uuid


TRACK_ATTRIBUTE_KEYS = ("name", "notes", "type", "stage", "status", "widthM")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _width(value):
    if value is None or str(value) == "NULL":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def editable_value(feature):
    attributes = {
        "name": feature.get("name"),
        "notes": feature.get("notes"),
    }
    if feature.get("kind") == "managed_tracks":
        attributes.update(
            {
                "type": feature.get("type") or "access_track",
                "stage": feature.get("stage") or "actual",
                "status": feature.get("status") or "published",
                "widthM": _width(feature.get("widthM")),
            }
        )
    return {
        "geometry": feature["geometry"],
        "kind": feature["kind"],
        "attributes": attributes,
    }


def changes_between(baseline, current, identities):
    """Stable change IDs survive timeout/retry; changing a payload gets a new ID."""
    changes = []
    for key in sorted(set(baseline) | set(current)):
        before, after = baseline.get(key), current.get(key)
        if before and after and editable_value(before) == editable_value(after):
            continue
        if before and not before.get("editable", True):
            raise ValueError("A protected Collar feature has local changes. Reload it before synchronising.")
        if not before:
            change = {"action": "create", **editable_value(after)}
        elif not after:
            change = {"action": "delete", "id": before["id"], "revision": before["revision"]}
        else:
            change = {"action": "update", "id": before["id"], "revision": before["revision"], **editable_value(after)}
        signature = canonical(change)
        entry = identities.get(key)
        if not entry or entry["signature"] != signature:
            entry = {"signature": signature, "changeId": str(uuid.uuid4())}
            identities[key] = entry
        changes.append((key, {"changeId": entry["changeId"], **change}))
    return changes


def acknowledge(baseline, submitted, results):
    """Advance only applied snapshots. Conflicts and later local edits remain dirty."""
    updated = copy.deepcopy(baseline)
    by_id = {result["changeId"]: result for result in results}
    for key, change in submitted:
        result = by_id.get(change["changeId"], {})
        if result.get("status") != "applied":
            continue
        if change["action"] == "delete":
            updated.pop(key, None)
        else:
            row = {
                "id": result["id"],
                "revision": result["revision"],
                "editable": True,
                "kind": change["kind"],
                "geometry": change["geometry"],
                **change["attributes"],
            }
            updated[key] = row
    return updated


def batch_length(queue, max_changes=50, max_vertices=5000):
    """Respect the same work bounds as the Worker, before starting a network request."""
    def count(value):
        if not isinstance(value, list):
            return 0
        return 1 if value and isinstance(value[0], (int, float)) else sum(count(v) for v in value)
    total, length = 0, 0
    for _layer, _key, change in queue[:max_changes]:
        vertices = count(change.get('geometry', {}).get('coordinates', []))
        limit = 5000 if change.get('kind') == 'managed_tracks' else 1000
        if vertices > limit:
            raise ValueError(
                'Simplify each {} to at most {:,} vertices before synchronising.'.format(
                    'track' if change.get('kind') == 'managed_tracks' else 'geometry',
                    limit,
                )
            )
        if total + vertices > max_vertices:
            break
        length += 1
        total += vertices
    return length

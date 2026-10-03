"""Fail-closed media capacity check for Rolixa.

Video files never use Supabase Storage. At least one object-storage backend must
be configured, and the next render must fit inside a conservative free-mode cap.
"""
import os
import sys

from r2_storage import configured as r2_configured, usage_bytes as r2_usage
from b2_storage import configured as b2_configured, usage_bytes as b2_usage

EXPECTED_RENDER_BYTES = int(os.environ.get("ROLIXA_EXPECTED_RENDER_BYTES", str(750 * 1024 * 1024)))
HEADROOM_BYTES = int(os.environ.get("ROLIXA_STORAGE_HEADROOM_BYTES", str(250 * 1024 * 1024)))


def check(name, configured, usage, limit):
    if not configured:
        return {"name": name, "configured": False, "usable": False}
    used = int(usage())
    remaining = max(0, int(limit) - used)
    usable = remaining >= EXPECTED_RENDER_BYTES + HEADROOM_BYTES
    return {
        "name": name,
        "configured": True,
        "used_bytes": used,
        "limit_bytes": int(limit),
        "remaining_bytes": remaining,
        "usable_for_next_render": usable,
    }


def main():
    checks = []
    if r2_configured():
        checks.append(check(
            "r2", True, r2_usage,
            int(os.environ.get("ROLIXA_R2_MAX_STORAGE_BYTES", str(int(9.5 * 1_000_000_000))))
        ))
    else:
        checks.append({"name": "r2", "configured": False, "usable_for_next_render": False})

    if b2_configured():
        checks.append(check(
            "b2", True, b2_usage,
            int(os.environ.get("ROLIXA_B2_MAX_STORAGE_BYTES", str(9_000_000_000)))
        ))
    else:
        checks.append({"name": "b2", "configured": False, "usable_for_next_render": False})

    usable = [x for x in checks if x.get("usable_for_next_render")]
    print({"backends": checks, "expected_render_bytes": EXPECTED_RENDER_BYTES, "headroom_bytes": HEADROOM_BYTES})

    if not usable:
        print(
            "ERROR: no media backend has enough protected capacity for the next render. "
            "Rolixa refuses to render rather than recreate the storage-over-quota failure.",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()

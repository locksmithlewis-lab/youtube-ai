
import os
import sys

from r2_storage import configured as r2_configured, usage_bytes as r2_usage

EXPECTED_RENDER_BYTES = int(os.environ.get("ROLIXA_EXPECTED_RENDER_BYTES", str(750 * 1024 * 1024)))
HEADROOM_BYTES = int(os.environ.get("ROLIXA_STORAGE_HEADROOM_BYTES", str(250 * 1024 * 1024)))


def check(name, is_configured, usage, limit):
    if not is_configured:
        return {"name": name, "configured": False, "usable_for_next_render": False}
    used = int(usage())
    remaining = max(0, int(limit) - used)
    return {
        "name": name,
        "configured": True,
        "used_bytes": used,
        "limit_bytes": int(limit),
        "remaining_bytes": remaining,
        "usable_for_next_render": remaining >= EXPECTED_RENDER_BYTES + HEADROOM_BYTES,
    }


def main():
    # R2 is the only automatic media backend. B2 requires explicit opt-in so
    # Rolixa cannot unexpectedly create a second cloud-storage bill.
    r2 = check(
        "r2",
        r2_configured(),
        r2_usage,
        int(os.environ.get("ROLIXA_R2_MAX_STORAGE_BYTES", str(int(9.0 * 1_000_000_000))))
    )
    print({
        "media_backend": "r2",
        "storage": r2,
        "expected_render_bytes": EXPECTED_RENDER_BYTES,
        "headroom_bytes": HEADROOM_BYTES,
    })
    if not r2.get("usable_for_next_render"):
        print(
            "ERROR: Cloudflare R2 is not configured or does not have enough protected "
            "capacity for the next render. Rolixa refuses to render instead of risking "
            "a storage-quota failure.",
            file=sys.stderr,
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()

"""Safety checks that gate publication of a new blocklist."""

MIN_TOTAL = 5000
MAX_TOTAL = 150000
LIMITS = {"full": (MIN_TOTAL, MAX_TOTAL), "lite": (1000, 20000)}
MAX_DROP = 0.5
MAX_GROWTH = 2.0


def safety_errors(
    total: int,
    previous_total: int | None,
    failed_required: list[str],
    min_total: int = MIN_TOTAL,
    max_total: int = MAX_TOTAL,
    max_drop: float = MAX_DROP,
    max_growth: float = MAX_GROWTH,
    allow_growth: bool = False,
    explained_drop: int = 0,
) -> list[str]:
    """Return a list of problems; an empty list means it is safe to publish.

    allow_growth skips only the growth check (for an expected jump, such as
    a new source); every other check still applies. explained_drop is how many
    previous entries came from optional sources that failed this run: a drop no
    larger than that skips only the drop check.
    """
    errors: list[str] = []
    if failed_required:
        errors.append("required sources failed: " + ", ".join(failed_required))
    if total < min_total:
        errors.append(f"total {total} is below the minimum {min_total}")
    if total > max_total:
        errors.append(f"total {total} is above the maximum {max_total}")
    if (previous_total and total < previous_total * (1 - max_drop)
            and previous_total - total > explained_drop):
        errors.append(
            f"total {total} dropped more than {max_drop:.0%} from previous {previous_total}"
        )
    if not allow_growth and previous_total and total > previous_total * max_growth:
        errors.append(
            f"total {total} grew more than {max_growth:g}x from previous {previous_total}"
        )
    return errors

import logging
import math
from typing import List, Tuple

logger = logging.getLogger("guardrails")

ALLOWED_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

REQUIRED_ADJ_KEYS = {
    "solar_reduction": {"hours", "factor"},
    "minimum_battery_reserve": {"hours", "minimum_energy_kwh"},
    "no_charge_window": {"hours"},
    "no_discharge_window": {"hours"},
    "max_grid_window": {"hours", "max_grid_kwh"},
}


def _is_finite_number(val) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def _no_op_entry(note_index: int, reason: str) -> dict:
    return {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": reason,
    }


def _valid_hours(hours) -> bool:
    if not isinstance(hours, list) or len(hours) == 0:
        return False
    if not all(isinstance(h, int) and not isinstance(h, bool) for h in hours):
        return False
    if len(set(hours)) != len(hours):
        return False
    if hours != sorted(hours):
        return False
    if any(h < 0 or h > 23 for h in hours):
        return False
    return True


def _validate_entry(entry: dict, battery_capacity_kwh: float) -> Tuple[dict, bool]:
    """Returns (cleaned_entry, malformed). malformed=True means the raw entry was
    coerced to no_op because it was structurally/semantically invalid — NOT because
    the LLM legitimately judged the note irrelevant. Callers use `malformed` to decide
    whether a provider's output should be trusted or retried with a fallback provider."""
    if not isinstance(entry, dict):
        return None, True

    note_index = entry.get("note_index")
    if not isinstance(note_index, int) or isinstance(note_index, bool):
        return None, True

    directive_type = entry.get("directive_type")
    # directive_type could be a list/dict/etc — guard membership check against unhashable types.
    if not isinstance(directive_type, str) or directive_type not in ALLOWED_TYPES:
        return _no_op_entry(note_index, "Unsupported directive type; coerced to no_op."), True

    applies = entry.get("applies")

    if directive_type == "no_op":
        if applies not in (False, None):
            # Model said no_op but applies=true — inconsistent, but no_op semantics win by spec.
            logger.warning("Note %s: no_op with applies=%r; normalized to applies=false.", note_index, applies)
        return _no_op_entry(note_index, entry.get("explanation") or "Note does not affect the schedule."), False

    if applies is not True:
        return _no_op_entry(note_index, "Non-no_op directive missing applies=true; coerced to no_op."), True

    adj = entry.get("structured_adjustment")
    if not isinstance(adj, dict):
        return _no_op_entry(note_index, "Missing/invalid structured_adjustment; coerced to no_op."), True

    required_keys = REQUIRED_ADJ_KEYS[directive_type]
    if not required_keys.issubset(adj.keys()):
        return _no_op_entry(note_index, "structured_adjustment missing required keys; coerced to no_op."), True

    hours = adj.get("hours")
    if not _valid_hours(hours):
        return _no_op_entry(note_index, "Invalid hours array; coerced to no_op."), True

    if directive_type == "solar_reduction":
        factor = adj.get("factor")
        if not _is_finite_number(factor) or not (0 <= factor <= 1):
            return _no_op_entry(note_index, "Invalid solar_reduction factor; coerced to no_op."), True
        clean_adj = {"hours": hours, "factor": float(factor)}

    elif directive_type == "minimum_battery_reserve":
        val = adj.get("minimum_energy_kwh")
        if not _is_finite_number(val) or val < 0 or val > battery_capacity_kwh:
            return _no_op_entry(note_index, "Invalid minimum_energy_kwh; coerced to no_op."), True
        clean_adj = {"hours": hours, "minimum_energy_kwh": float(val)}

    elif directive_type == "no_charge_window":
        clean_adj = {"hours": hours}

    elif directive_type == "no_discharge_window":
        clean_adj = {"hours": hours}

    elif directive_type == "max_grid_window":
        val = adj.get("max_grid_kwh")
        if not _is_finite_number(val) or val < 0:
            return _no_op_entry(note_index, "Invalid max_grid_kwh (must be finite and non-negative); coerced to no_op."), True
        clean_adj = {"hours": hours, "max_grid_kwh": float(val)}

    else:
        return _no_op_entry(note_index, "Unhandled directive type; coerced to no_op."), True

    return {
        "note_index": note_index,
        "applies": True,
        "directive_type": directive_type,
        "structured_adjustment": clean_adj,
        "explanation": str(entry.get("explanation") or ""),
    }, False


def validate_directives(
    raw_directives: list, num_notes: int, battery_capacity_kwh: float
) -> Tuple[List[dict], bool]:
    """Deterministically validates/coerces raw LLM directive output.
    Guarantees: returns exactly num_notes entries, one per note_index in ascending order,
    each either a fully valid non-no_op directive or a safe no_op. Never raises.

    Returns (entries, all_valid). all_valid is False if ANY note's raw entry was
    missing, duplicated, or structurally/semantically malformed — signaling that this
    provider's output should not be trusted as-is and a fallback provider should be
    tried instead. It is True only when every note produced a clean, directly-usable
    interpretation (including a legitimate LLM-declared no_op)."""
    by_index: dict = {}
    malformed_seen = False
    seen_raw_indices = set()

    for raw_entry in raw_directives or []:
        cleaned, malformed = _validate_entry(raw_entry, battery_capacity_kwh)
        if cleaned is None:
            malformed_seen = True
            continue
        idx = cleaned["note_index"]
        if idx is None or idx < 0 or idx >= num_notes:
            malformed_seen = True
            continue
        if idx in seen_raw_indices:
            # Duplicate note_index in the LLM's raw output — untrustworthy output.
            malformed_seen = True
            continue
        seen_raw_indices.add(idx)
        if malformed:
            malformed_seen = True
        by_index[idx] = cleaned

    result = []
    for i in range(num_notes):
        if i in by_index:
            result.append(by_index[i])
        else:
            entry = _no_op_entry(i, "No valid interpretation returned; coerced to no_op.")
            logger.warning("Note %d missing/invalid interpretation; defaulted to no_op.", i)
            result.append(entry)
            malformed_seen = True

    return result, not malformed_seen

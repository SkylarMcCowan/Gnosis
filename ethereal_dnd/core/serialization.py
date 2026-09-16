"""to_dict()/from_dict() convention shared by every definition/instance
pair (design doc Section 8) - a lightweight alternative to a full ORM,
since Phase 0 only needs round-trip fidelity for save/load (a later
ticket), not validation beyond catching typos.
"""
import dataclasses


def to_dict(obj) -> dict:
    """Convert a dataclass instance to a plain dict, recursing into nested
    dataclasses. Raises TypeError for anything that isn't a dataclass -
    callers should not pass a bare dict expecting it to pass through
    silently."""
    if not dataclasses.is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(f"{obj!r} is not a dataclass instance")
    return dataclasses.asdict(obj)


def from_dict(cls, data: dict):
    """Reconstruct a dataclass instance of `cls` from a plain dict
    produced by to_dict(). Does not recurse into nested dataclass fields
    automatically - callers with nested structures pass already-
    constructed nested instances in `data` (build bottom-up), since
    generically inferring nested dataclass types from a dict is out of
    scope for this minimal implementation.

    Raises ValueError on any field in `data` that isn't a real field of
    `cls`, rather than silently dropping it - a typo in a save file
    should surface as an error, not a quietly-missing value.
    """
    if not dataclasses.is_dataclass(cls) or not isinstance(cls, type):
        raise TypeError(f"{cls!r} is not a dataclass type")
    field_names = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - field_names
    if unknown:
        raise ValueError(f"Unknown field(s) for {cls.__name__}: {sorted(unknown)}")
    return cls(**data)

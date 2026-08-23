"""Shared filtering/sorting primitives for FabOS tables."""
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional

@dataclass
class ListFilter:
    query: str = ""
    sort_key: Optional[str] = None
    descending: bool = False

def apply_filter(rows: Iterable[Any], spec: ListFilter,
                 text_getter: Callable[[Any], str] = str) -> List[Any]:
    result = list(rows)
    q = (spec.query or "").strip().lower()
    if q:
        result = [r for r in result if q in text_getter(r).lower()]
    if spec.sort_key:
        def key(row):
            if isinstance(row, dict):
                return row.get(spec.sort_key)
            return getattr(row, spec.sort_key, None)
        result.sort(key=lambda x: (key(x) is None, key(x)),
                    reverse=spec.descending)
    return result

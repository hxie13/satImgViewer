from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class FileGroup:
    """A timestamp-like group of files that represent one frame."""

    key: str
    files: List[str]


@dataclass(frozen=True)
class RenderRequest:
    """Structured image render input contract."""

    bands: Sequence[str]
    size: Optional[Tuple[int, int]] = (1000, 1000)
    gamma: float = 1.0
    proj_name: str = "plate_carree_global"


@dataclass
class RenderResult:
    """Structured image render output contract."""

    image_data: "np.ndarray"
    area_def: Any
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportResult:
    """Standardized export status payload used by UI and workers."""

    status: str
    path: str
    time_s: float

"""Tool modules — importing any of these registers tools on the shared FastMCP instance."""
from . import runs  # noqa: F401 — registered first so it's the discoverable opener
from . import bundle  # noqa: F401
from . import validate  # noqa: F401
from . import package  # noqa: F401
from . import upload  # noqa: F401
from . import notebook  # noqa: F401 — stage-by-stage starting_kit.ipynb authoring

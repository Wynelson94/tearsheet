"""tearsheet: local web-to-markdown for LLM research — scrape, crawl, map, search, extract.

Import callables from their modules (re-exporting them here would shadow the
same-named submodules): ``from tearsheet.scrape import scrape``, etc.
"""

from tearsheet.mapper import map_site
from tearsheet.structured import extract_page, extract_structured

__version__ = "0.1.0"

__all__ = ["__version__", "extract_page", "extract_structured", "map_site"]

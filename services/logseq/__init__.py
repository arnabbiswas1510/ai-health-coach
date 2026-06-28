# services/logseq/__init__.py
from .logseq_client import build_props, write_daily_properties, write_props_dict

__all__ = ["build_props", "write_daily_properties", "write_props_dict"]

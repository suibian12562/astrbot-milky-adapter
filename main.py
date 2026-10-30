"""Importing the plugin registers its platform adapter with AstrBot."""
from astrbot.api.star import Context, Star

from .adapter import MilkyAdapter  # noqa: F401


class MilkyAdapterPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

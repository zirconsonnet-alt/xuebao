"""视觉服务实现。"""

from src.support.core import Services

from ._vision.commands import VisionCommandMixin
from .base import BaseService, config_property


class VisionService(VisionCommandMixin, BaseService):
    service_type = Services.Vision
    default_config = {
        "enabled": True,
    }
    enabled = config_property("enabled")


__all__ = ["VisionService"]

"""视觉能力上游调用聚合层。"""

from .describe_api import VisionDescribeApiMixin
from .image_generation_api import ImageGenerationApiMixin


class VisionApiMixin(VisionDescribeApiMixin, ImageGenerationApiMixin):
    pass


__all__ = ["VisionApiMixin"]

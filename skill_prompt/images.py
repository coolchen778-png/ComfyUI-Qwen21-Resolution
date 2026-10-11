import base64
import io
from collections.abc import Sequence

import torch
from PIL import Image

from .errors import SkillPromptError


def tensor_to_pil(image: torch.Tensor) -> Image.Image:
    if not isinstance(image, torch.Tensor) or image.ndim != 4:
        raise SkillPromptError("图片转换", "IMAGE 必须是 [B, H, W, C] tensor")
    if image.shape[0] != 1:
        raise SkillPromptError("图片转换", "每个图片端口只接受 batch=1")
    channels = image.shape[-1]
    if channels not in (1, 3, 4):
        raise SkillPromptError("图片转换", "图片通道数必须是 1、3 或 4")

    pixels = image[0].detach().to(device="cpu", dtype=torch.float32)
    pixels = torch.nan_to_num(pixels, nan=0.0, posinf=1.0, neginf=0.0).clamp(0.0, 1.0)
    if channels == 1:
        pixels = pixels.repeat(1, 1, 3)
    elif channels == 4:
        pixels = pixels[..., :3]
    array = pixels.mul(255).round().to(torch.uint8).numpy()
    return Image.fromarray(array)


def prepare_images(values: Sequence[torch.Tensor | None]) -> tuple[Image.Image, ...]:
    if len(values) > 5:
        raise SkillPromptError("图片转换", "最多支持 5 张参考图")
    return tuple(tensor_to_pil(value) for value in values if value is not None)


def resize_for_api(image: Image.Image, max_side: int) -> Image.Image:
    if max_side < 0:
        raise SkillPromptError("图片转换", "在线图片最大边长不能为负数")
    if max_side == 0 or max(image.size) <= max_side:
        return image
    scale = max_side / max(image.size)
    size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    return image.resize(size, Image.Resampling.LANCZOS)


def image_to_data_uri(image: Image.Image, max_side: int) -> str:
    converted = resize_for_api(image.convert("RGB"), max_side)
    buffer = io.BytesIO()
    converted.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"

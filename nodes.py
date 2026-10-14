import torch
import torch.nn.functional as F

try:
    from .skill_prompt.node import QwenMultiSkillPromptGenerator, QwenSkillLoader
except ImportError:
    from skill_prompt.node import QwenMultiSkillPromptGenerator, QwenSkillLoader

try:
    import comfy.utils
    HAS_COMFY = True
except ImportError:
    HAS_COMFY = False


# Qwen 2.1 官方推荐分辨率表: (宽, 高, 宽高比名称, 理论比例 W/H)
QWEN21_RESOLUTIONS = [
    (2048, 2048, "1:1", 1.0 / 1.0),
    (2400, 1792, "4:3", 4.0 / 3.0),
    (1792, 2400, "3:4", 3.0 / 4.0),
    (2528, 1696, "3:2", 3.0 / 2.0),
    (1696, 2528, "2:3", 2.0 / 3.0),
    (2752, 1536, "16:9", 16.0 / 9.0),
    (1536, 2752, "9:16", 9.0 / 16.0),
]

PRESET_MAP = {
    f"{ratio} ({w}x{h})": (w, h, ratio)
    for w, h, ratio, _ in QWEN21_RESOLUTIONS
}


def find_closest_qwen21_resolution(width: int, height: int):
    """根据输入宽高的比例，匹配最接近的 Qwen 2.1 官方推荐分辨率"""
    if height <= 0 or width <= 0:
        return 2048, 2048, "1:1"

    input_ratio = width / height
    # 使用对数比例差 abs(log(r1) - log(r2)) 或直接比例差来衡量相似度
    # 对数距离在横竖屏对称性上更优（例如 4:3 与 3:4 对称）
    import math
    log_input = math.log(input_ratio)

    best_match = QWEN21_RESOLUTIONS[0]
    min_diff = float("inf")

    for w, h, name, target_ratio in QWEN21_RESOLUTIONS:
        # 比较输入宽高比与目标实际分辨率比例 (w / h) 的对数距离
        actual_ratio = w / h
        diff = abs(log_input - math.log(actual_ratio))
        if diff < min_diff:
            min_diff = diff
            best_match = (w, h, name, target_ratio)

    return best_match[0], best_match[1], best_match[2]


class Qwen21ResolutionResize:
    """
    Qwen 2.1 自动分辨率识别与缩放节点
    自动根据输入图像的宽高比匹配 Qwen 2.1 官方推荐分辨率并缩放图像，同时输出 width 和 height。
    """

    UPSUL_METHODS = ["lanczos", "bicubic", "bilinear", "nearest-exact", "area"]
    CROP_METHODS = ["disabled", "center"]
    PRESET_OPTIONS = ["auto"] + list(PRESET_MAP.keys())

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "preset": (cls.PRESET_OPTIONS, {"default": "auto"}),
                "upscale_method": (cls.UPSUL_METHODS, {"default": "lanczos"}),
                "crop": (cls.CROP_METHODS, {"default": "disabled"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "width", "height", "aspect_ratio")
    FUNCTION = "resize_to_qwen21"
    CATEGORY = "cbkk"

    def resize_to_qwen21(self, image: torch.Tensor, preset: str = "auto", upscale_method: str = "lanczos", crop: str = "disabled"):
        # ComfyUI IMAGE 格式为 [B, H, W, C]
        _, orig_h, orig_w, _ = image.shape

        if preset == "auto" or preset not in PRESET_MAP:
            target_w, target_h, ratio_name = find_closest_qwen21_resolution(orig_w, orig_h)
        else:
            target_w, target_h, ratio_name = PRESET_MAP[preset]

        # 如果尺寸已经完全一致，直接返回原图
        if orig_w == target_w and orig_h == target_h:
            return (image, target_w, target_h, ratio_name)

        # 转换为 [B, C, H, W] 进行缩放
        samples = image.movedim(-1, 1)

        if HAS_COMFY:
            resized = comfy.utils.common_upscale(samples, target_w, target_h, upscale_method, crop)
        else:
            # 脱离 ComfyUI 环境时的回退实现
            mode = "bicubic" if upscale_method in ("lanczos", "bicubic") else (
                "nearest" if upscale_method == "nearest-exact" else upscale_method
            )
            align_corners = False if mode in ("bicubic", "bilinear") else None
            resized = F.interpolate(samples, size=(target_h, target_w), mode=mode, align_corners=align_corners)

        # 转回 [B, H, W, C]
        out_image = resized.movedim(1, -1)
        return (out_image, int(target_w), int(target_h), ratio_name)


NODE_CLASS_MAPPINGS = {
    "Qwen21ResolutionResize": Qwen21ResolutionResize,
    "QwenMultiSkillPromptGenerator": QwenMultiSkillPromptGenerator,
    "QwenSkillLoader": QwenSkillLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Qwen21ResolutionResize": "cbkk｜Qwen 2.1 分辨率自动匹配",
    "QwenMultiSkillPromptGenerator": "cbkk｜Skill 提示词生成器",
    "QwenSkillLoader": "cbkk｜Skill 知识库加载器",
}

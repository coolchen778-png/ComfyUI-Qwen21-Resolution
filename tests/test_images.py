import base64
import io

import pytest
import torch
from PIL import Image

from skill_prompt.errors import SkillPromptError
from skill_prompt.images import (
    image_to_data_uri,
    prepare_images,
    resize_for_api,
    tensor_to_pil,
)


def test_tensor_to_pil_clamps_and_normalizes_nonfinite_rgb_values():
    tensor = torch.tensor(
        [[[[float("nan"), -1.0, 0.5], [float("inf"), 2.0, float("-inf")]]]]
    )

    image = tensor_to_pil(tensor)

    assert image.mode == "RGB"
    assert image.size == (2, 1)
    assert list(image.getdata()) == [(0, 0, 128), (255, 255, 0)]


def test_tensor_to_pil_converts_grayscale_and_rgba_to_rgb():
    gray = torch.tensor([[[[0.25], [0.75]]]])
    rgba = torch.tensor([[[[1.0, 0.0, 0.5, 0.1]]]])

    gray_image = tensor_to_pil(gray)
    rgba_image = tensor_to_pil(rgba)

    assert list(gray_image.getdata()) == [(64, 64, 64), (191, 191, 191)]
    assert list(rgba_image.getdata()) == [(255, 0, 128)]


@pytest.mark.parametrize(
    "tensor",
    [
        torch.zeros((2, 4, 4, 3)),
        torch.zeros((4, 4, 3)),
        torch.zeros((1, 4, 4, 2)),
    ],
)
def test_tensor_to_pil_rejects_batch_shape_or_channels(tensor):
    with pytest.raises(SkillPromptError) as error:
        tensor_to_pil(tensor)

    assert error.value.stage == "图片转换"


def test_prepare_images_skips_none_and_preserves_port_order():
    red = torch.tensor([[[[1.0, 0.0, 0.0]]]])
    blue = torch.tensor([[[[0.0, 0.0, 1.0]]]])

    images = prepare_images([None, red, None, blue, None])

    assert [image.getpixel((0, 0)) for image in images] == [(255, 0, 0), (0, 0, 255)]


def test_prepare_images_rejects_more_than_five_ports():
    with pytest.raises(SkillPromptError, match="最多支持 5 张"):
        prepare_images([None] * 6)


def test_resize_for_api_preserves_ratio_and_zero_keeps_original():
    image = Image.new("RGB", (400, 200), "white")

    resized = resize_for_api(image, 100)

    assert resized.size == (100, 50)
    assert resize_for_api(image, 0) is image


def test_image_to_data_uri_contains_decodable_png():
    image = Image.new("RGB", (8, 4), (12, 34, 56))

    uri = image_to_data_uri(image, 4)
    prefix, encoded = uri.split(",", 1)
    decoded = Image.open(io.BytesIO(base64.b64decode(encoded)))

    assert prefix == "data:image/png;base64"
    assert decoded.size == (4, 2)
    assert decoded.convert("RGB").getpixel((0, 0)) == (12, 34, 56)


def test_resize_for_api_rejects_negative_limit():
    with pytest.raises(SkillPromptError, match="不能为负数"):
        resize_for_api(Image.new("RGB", (1, 1)), -1)

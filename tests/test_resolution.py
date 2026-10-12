import torch

from nodes import Qwen21ResolutionResize, find_closest_qwen21_resolution


def test_existing_resolution_matcher_is_preserved():
    assert find_closest_qwen21_resolution(1920, 1080) == (2752, 1536, "16:9")
    assert find_closest_qwen21_resolution(0, 0) == (2048, 2048, "1:1")


def test_existing_resolution_node_contract_and_output():
    assert Qwen21ResolutionResize.RETURN_TYPES == ("IMAGE", "INT", "INT", "STRING")
    assert Qwen21ResolutionResize.CATEGORY == "cbkk"
    image = torch.zeros((1, 8, 8, 3))
    output, width, height, ratio = Qwen21ResolutionResize().resize_to_qwen21(
        image, preset="1:1 (2048x2048)"
    )
    assert output.shape == (1, 2048, 2048, 3)
    assert (width, height, ratio) == (2048, 2048, "1:1")

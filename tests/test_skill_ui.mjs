import test from "node:test";
import assert from "node:assert/strict";

import {
    MODE_API,
    MODE_LOCAL,
    VISIBLE_BACKEND_CHOICES,
    isWidgetVisible,
    modelKind,
    normalizeMode,
} from "../web/js/qwen_skill_prompt_ui.mjs";


test("normalizes Chinese and legacy backend values to two UI modes", () => {
    assert.deepEqual(VISIBLE_BACKEND_CHOICES, ["本地模型", "在线 API"]);
    assert.equal(normalizeMode("本地模型"), MODE_LOCAL);
    assert.equal(normalizeMode("gguf"), MODE_LOCAL);
    assert.equal(normalizeMode("transformers"), MODE_LOCAL);
    assert.equal(normalizeMode("在线 API"), MODE_API);
    assert.equal(normalizeMode("online_api"), MODE_API);
});


test("recognizes the selected local model kind", () => {
    assert.equal(modelKind("GGUF｜Qwen/model.gguf"), "gguf");
    assert.equal(modelKind("Transformers｜Qwen-VL"), "transformers");
    assert.equal(modelKind("请选择本地模型"), "unknown");
});


test("local mode shows one model selector and only shows mmproj for GGUF", () => {
    assert.equal(isWidgetVisible("local_model", MODE_LOCAL, "GGUF｜m.gguf"), true);
    assert.equal(isWidgetVisible("local_mmproj", MODE_LOCAL, "GGUF｜m.gguf"), true);
    assert.equal(
        isWidgetVisible("local_mmproj", MODE_LOCAL, "Transformers｜Qwen-VL"),
        false,
    );
    assert.equal(isWidgetVisible("api_base_url", MODE_LOCAL, "GGUF｜m.gguf"), false);
    assert.equal(isWidgetVisible("gguf_model_path", MODE_LOCAL, "GGUF｜m.gguf"), false);
    assert.equal(isWidgetVisible("transformers_model", MODE_LOCAL, "GGUF｜m.gguf"), false);
});


test("API mode hides local selectors and shows API settings", () => {
    assert.equal(isWidgetVisible("local_model", MODE_API, "GGUF｜m.gguf"), false);
    assert.equal(isWidgetVisible("local_mmproj", MODE_API, "GGUF｜m.gguf"), false);
    assert.equal(isWidgetVisible("api_base_url", MODE_API, "GGUF｜m.gguf"), true);
    assert.equal(isWidgetVisible("api_model", MODE_API, "GGUF｜m.gguf"), true);
});

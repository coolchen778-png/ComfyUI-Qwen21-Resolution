export const MODE_LOCAL = "local";
export const MODE_API = "api";
export const CBKK_NODE_NAMES = Object.freeze([
    "Qwen21ResolutionResize",
    "QwenMultiSkillPromptGenerator",
    "QwenSkillLoader",
    "QwenSkillPromptPreview",
]);

export function setCbkkNodeSource(defs) {
    if (!defs || typeof defs !== "object") return defs;
    for (const nodeName of CBKK_NODE_NAMES) {
        const definition = defs[nodeName];
        if (definition && typeof definition === "object") {
            definition.python_module = "custom_nodes.cbkk";
        }
    }
    return defs;
}
export const VISIBLE_BACKEND_CHOICES = Object.freeze(["本地模型", "在线 API"]);

export const WIDGET_LABELS = Object.freeze({
    task: "任务描述",
    backend: "运行方式",
    local_model: "主模型",
    local_mmproj: "视觉投影模型（mmproj）",
    role_prompt: "角色提示词",
    max_new_tokens: "最大生成 Token",
    temperature: "温度",
    seed: "随机种子",
    strip_thinking: "移除思考过程",
    unload_after_generate: "生成后卸载模型",
    gguf_n_ctx: "上下文长度 (Token 上限)",
    api_base_url: "API 地址",
    api_model: "API 模型名",
    api_key_env: "API Key 环境变量",
    api_custom_headers: "自定义请求头（JSON）",
    api_timeout: "API 超时（秒）",
    api_max_image_side: "API 图片最长边",
});

export function normalizeMode(value) {
    if (value === "在线 API" || value === "online_api") return MODE_API;
    return MODE_LOCAL;
}

export function modelKind(selection) {
    if (typeof selection !== "string") return "unknown";
    if (selection.startsWith("GGUF｜")) return "gguf";
    if (selection.startsWith("Transformers｜")) return "transformers";
    return "unknown";
}

export function isWidgetVisible(name, mode, localModelSelection) {
    if (name === "local_model") return mode === MODE_LOCAL;
    if (name === "local_mmproj") {
        return mode === MODE_LOCAL && modelKind(localModelSelection) !== "transformers";
    }
    if (name === "gguf_n_ctx") {
        return mode === MODE_LOCAL && modelKind(localModelSelection) === "gguf";
    }
    if (name.startsWith("api_")) return mode === MODE_API;
    if (name.startsWith("gguf_") || name.startsWith("transformers_")) return false;
    return true;
}

export function extractPromptFromExecutedMessage(message) {
    if (!message) return "";
    let val = message.text ?? message.output?.text ?? message;
    if (Array.isArray(val)) {
        val = val.join("\n");
    }
    if (typeof val === "string") return val;
    if (typeof val === "object") {
        try {
            return JSON.stringify(val, null, 2);
        } catch {
            return String(val);
        }
    }
    return String(val || "");
}

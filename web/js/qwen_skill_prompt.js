import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
    VISIBLE_BACKEND_CHOICES,
    WIDGET_LABELS,
    isWidgetVisible,
    normalizeMode,
} from "./qwen_skill_prompt_ui.mjs";

const NODE_NAME = "QwenMultiSkillPromptGenerator";

function setWidgetVisible(node, widget, visible) {
    if (!widget.__cbkkOriginalComputeSize) {
        widget.__cbkkOriginalComputeSize = widget.computeSize?.bind(widget);
    }
    widget.hidden = !visible;
    widget.computeSize = visible
        ? widget.__cbkkOriginalComputeSize
        : () => [0, -4];
    node.setDirtyCanvas(true, true);
}

function localizeWidgets(node) {
    for (const widget of node.widgets || []) {
        if (WIDGET_LABELS[widget.name]) widget.label = WIDGET_LABELS[widget.name];
    }
}

function syncModeWidgets(node) {
    const backend = node.widgets?.find((widget) => widget.name === "backend");
    const localModel = node.widgets?.find((widget) => widget.name === "local_model");
    const mode = normalizeMode(backend?.value);
    for (const widget of node.widgets || []) {
        if (widget.name === "skills" || widget.name?.startsWith("cbkk_skill_")) continue;
        setWidgetVisible(
            node,
            widget,
            isWidgetVisible(widget.name || "", mode, localModel?.value),
        );
    }
    node.setSize(node.computeSize());
}

function parseSelection(widget) {
    try {
        const parsed = JSON.parse(widget.value || "[]");
        return Array.isArray(parsed)
            ? parsed.filter((id) => typeof id === "string")
            : [];
    } catch {
        return [];
    }
}

function makeButton(label, title, primary = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = title;
    button.style.cssText = [
        "padding:6px 10px",
        "border:1px solid #58736a",
        "border-radius:5px",
        `background:${primary ? "#26745f" : "#2d3431"}`,
        "color:#f2f5f4",
        "cursor:pointer",
        "font-weight:600",
    ].join(";");
    return button;
}

async function fetchSkills() {
    const response = await api.fetchApi("/qwen_skill_prompt/skills");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload.skills || [];
}

async function uploadSkill(file) {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await api.fetchApi("/qwen_skill_prompt/upload", {
        method: "POST",
        body: form,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
}

function installSkillPicker(node, widget) {
    let available = [];
    let selected = parseSelection(widget);
    let status = null;
    let render = () => {};

    const commit = () => {
        widget.value = JSON.stringify(selected);
        widget.callback?.(widget.value);
        node.setDirtyCanvas(true, true);
    };

    const load = async () => {
        if (status) status.textContent = "正在扫描 Skill…";
        try {
            available = await fetchSkills();
            const known = new Set(available.map((entry) => entry.id));
            selected = selected.filter((id) => known.has(id));
            commit();
            render();
            if (status) status.textContent = `已选择 ${selected.length} 个 Skill`;
        } catch (error) {
            if (status) status.textContent = `Skill 加载失败：${error.message}`;
            else window.alert(`Skill 加载失败：${error.message}`);
        }
    };

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".md,.txt,text/plain,text/markdown";
    fileInput.hidden = true;
    fileInput.onchange = async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        if (status) status.textContent = `正在上传 ${file.name}…`;
        try {
            const entry = await uploadSkill(file);
            if (!selected.includes(entry.id)) selected.push(entry.id);
            await load();
        } catch (error) {
            if (status) status.textContent = `Skill 上传失败：${error.message}`;
            else window.alert(`Skill 上传失败：${error.message}`);
        } finally {
            fileInput.value = "";
        }
    };

    node.addWidget?.("button", "⬆ 上传 Skill 文件", null, () => fileInput.click(), {
        serialize: false,
    });
    node.addWidget?.("button", "↻ 刷新 Skill 列表", null, () => load(), {
        serialize: false,
    });

    if (typeof node.addDOMWidget !== "function") {
        widget.label = "Skill 选择（JSON；可使用上方上传按钮）";
        load();
        return;
    }

    setWidgetVisible(node, widget, false);
    const root = document.createElement("div");
    root.style.cssText = "display:flex;flex-direction:column;gap:7px;padding:8px;background:#202725;color:#e5ebe8;font:12px sans-serif;border:1px solid #3f514b;border-radius:6px;min-height:190px";

    const heading = document.createElement("div");
    heading.textContent = "Skill 联合选择（不限数量，可拖拽排序）";
    heading.style.cssText = "font-weight:700;color:#d8eee7";
    const toolbar = document.createElement("div");
    toolbar.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "搜索 Skill…";
    search.style.cssText = "flex:1;min-width:120px;background:#151918;color:#eee;border:1px solid #4a5551;border-radius:4px;padding:6px";
    const refresh = makeButton("↻ 刷新", "重新扫描 Skill 目录");
    const upload = makeButton("⬆ 上传 Skill", "上传 UTF-8 编码的 .md 或 .txt 文件", true);
    refresh.onclick = load;
    upload.onclick = () => fileInput.click();
    toolbar.append(search, upload, refresh, fileInput);

    const columns = document.createElement("div");
    columns.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:7px;min-height:130px";
    const choices = document.createElement("div");
    const chosen = document.createElement("div");
    for (const [element, title] of [
        [choices, "可选 Skill（点击添加）"],
        [chosen, "已选 Skill（拖拽排序）"],
    ]) {
        const label = document.createElement("div");
        label.textContent = title;
        label.style.cssText = "font-weight:700;margin-bottom:5px;color:#bcd2ca";
        element.append(label);
        element.style.cssText = "overflow:auto;max-height:230px;padding:6px;border:1px solid #3f4945;border-radius:4px;background:#171b1a";
    }
    columns.append(choices, chosen);
    status = document.createElement("div");
    status.style.cssText = "min-height:16px;color:#a9bbb4";
    root.append(heading, toolbar, columns, status);

    const labelFor = (id) =>
        available.find((entry) => entry.id === id)?.relative_path || id;
    render = () => {
        choices.replaceChildren();
        chosen.replaceChildren();
        const choicesTitle = document.createElement("div");
        choicesTitle.textContent = "可选 Skill（点击添加）";
        choicesTitle.style.cssText = "font-weight:700;margin-bottom:5px;color:#bcd2ca";
        choices.append(choicesTitle);
        const chosenTitle = document.createElement("div");
        chosenTitle.textContent = "已选 Skill（拖拽排序）";
        chosenTitle.style.cssText = "font-weight:700;margin-bottom:5px;color:#bcd2ca";
        chosen.append(chosenTitle);

        const query = search.value.trim().toLocaleLowerCase();
        for (const entry of available) {
            if (
                selected.includes(entry.id)
                || (query && !entry.id.toLocaleLowerCase().includes(query))
            ) continue;
            const button = makeButton(
                `${entry.source === "user" ? "用户" : "内置"}：${entry.relative_path}`,
                `添加 ${entry.id}`,
            );
            button.style.display = "block";
            button.style.width = "100%";
            button.style.marginBottom = "4px";
            button.onclick = () => {
                selected.push(entry.id);
                commit();
                render();
            };
            choices.append(button);
        }

        selected.forEach((id, index) => {
            const row = document.createElement("div");
            row.draggable = true;
            row.style.cssText = "display:flex;align-items:center;gap:5px;margin-bottom:4px;padding:4px;background:#29322f;border-radius:4px;cursor:grab";
            const handle = document.createElement("span");
            handle.textContent = "☰";
            const label = document.createElement("span");
            label.textContent = `${index + 1}. ${labelFor(id)}`;
            label.style.flex = "1";
            const remove = makeButton("×", `移除 ${id}`);
            remove.onclick = () => {
                selected.splice(index, 1);
                commit();
                render();
            };
            row.ondragstart = (event) =>
                event.dataTransfer.setData("text/plain", String(index));
            row.ondragover = (event) => event.preventDefault();
            row.ondrop = (event) => {
                event.preventDefault();
                const from = Number(event.dataTransfer.getData("text/plain"));
                if (Number.isInteger(from) && from !== index) {
                    const [moved] = selected.splice(from, 1);
                    selected.splice(index, 0, moved);
                    commit();
                    render();
                }
            };
            row.append(handle, label, remove);
            chosen.append(row);
        });
        status.textContent = `已选择 ${selected.length} 个 Skill`;
    };

    search.oninput = render;
    try {
        node.addDOMWidget("cbkk_skill_picker", "Skill 联合选择", root, {
            serialize: false,
        });
    } catch (error) {
        setWidgetVisible(node, widget, true);
        widget.label = "Skill 选择（JSON；可使用上传按钮）";
        console.warn("cbkk Skill 选择面板加载失败，已切换到兼容模式", error);
        load();
        return;
    }
    render();
    load();
}

app.registerExtension({
    name: "cbkk.qwen_multi_skill_prompt.zh_cn",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const original = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = original?.apply(this, arguments);
            localizeWidgets(this);
            const skills = this.widgets?.find((widget) => widget.name === "skills");
            const backend = this.widgets?.find((widget) => widget.name === "backend");
            const localModel = this.widgets?.find((widget) => widget.name === "local_model");
            if (backend?.options) {
                backend.options.values = [...VISIBLE_BACKEND_CHOICES];
            }
            if (skills) installSkillPicker(this, skills);
            for (const widget of [backend, localModel]) {
                if (!widget) continue;
                const callback = widget.callback;
                widget.callback = (...args) => {
                    callback?.apply(widget, args);
                    syncModeWidgets(this);
                };
            }
            syncModeWidgets(this);
            return result;
        };
    },
});

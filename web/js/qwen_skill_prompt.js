import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "QwenMultiSkillPromptGenerator";
const BACKEND_PREFIX = {
    gguf: "gguf_",
    transformers: "transformers_",
    online_api: "api_",
};

function setWidgetVisible(node, widget, visible) {
    if (!widget.__qwenOriginalComputeSize) {
        widget.__qwenOriginalComputeSize = widget.computeSize?.bind(widget);
    }
    widget.hidden = !visible;
    widget.computeSize = visible
        ? widget.__qwenOriginalComputeSize
        : () => [0, -4];
    node.setDirtyCanvas(true, true);
}

function syncBackendWidgets(node) {
    const backend = node.widgets?.find((widget) => widget.name === "backend")?.value;
    for (const widget of node.widgets || []) {
        const matched = Object.entries(BACKEND_PREFIX).find(([, prefix]) =>
            widget.name?.startsWith(prefix)
        );
        if (matched) {
            setWidgetVisible(node, widget, matched[0] === backend);
        }
    }
    node.setSize(node.computeSize());
}

function parseSelection(widget) {
    try {
        const parsed = JSON.parse(widget.value || "[]");
        return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
    } catch {
        return [];
    }
}

function makeButton(label, title) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = title;
    button.style.cssText = "padding:4px 8px;border:1px solid #555;border-radius:5px;background:#2d2d2d;color:#ddd;cursor:pointer";
    return button;
}

function installSkillPicker(node, widget) {
    setWidgetVisible(node, widget, false);
    let available = [];
    let selected = parseSelection(widget);

    const root = document.createElement("div");
    root.style.cssText = "display:flex;flex-direction:column;gap:6px;padding:7px;background:#202725;color:#ddd;font:12px sans-serif;border-radius:6px;min-height:170px";
    const toolbar = document.createElement("div");
    toolbar.style.cssText = "display:flex;gap:5px";
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "搜索 Skill…";
    search.style.cssText = "flex:1;background:#151918;color:#eee;border:1px solid #4a5551;border-radius:4px;padding:5px";
    const refresh = makeButton("刷新", "重新扫描 Skill 目录");
    const upload = makeButton("上传", "上传 UTF-8 .md/.txt Skill");
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".md,.txt,text/plain,text/markdown";
    fileInput.hidden = true;
    toolbar.append(search, refresh, upload, fileInput);

    const columns = document.createElement("div");
    columns.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:7px;min-height:130px";
    const choices = document.createElement("div");
    const chosen = document.createElement("div");
    for (const [element, title] of [[choices, "可选 Skill"], [chosen, "已选（拖拽排序）"]]) {
        element.dataset.title = title;
        element.style.cssText = "overflow:auto;max-height:210px;padding:5px;border:1px solid #3f4945;border-radius:4px;background:#171b1a";
    }
    columns.append(choices, chosen);
    const status = document.createElement("div");
    status.style.cssText = "min-height:16px;color:#9eaaa5";
    root.append(toolbar, columns, status);

    const commit = () => {
        widget.value = JSON.stringify(selected);
        widget.callback?.(widget.value);
        node.setDirtyCanvas(true, true);
    };

    const labelFor = (id) => available.find((entry) => entry.id === id)?.relative_path || id;
    const render = () => {
        choices.replaceChildren();
        chosen.replaceChildren();
        const query = search.value.trim().toLocaleLowerCase();
        for (const entry of available) {
            if (selected.includes(entry.id) || (query && !entry.id.toLocaleLowerCase().includes(query))) continue;
            const button = makeButton(`${entry.source}: ${entry.relative_path}`, `添加 ${entry.id}`);
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
            row.dataset.index = String(index);
            row.style.cssText = "display:flex;align-items:center;gap:5px;margin-bottom:4px;padding:4px;background:#29322f;border-radius:4px;cursor:grab";
            const handle = document.createElement("span");
            handle.textContent = "↕";
            const label = document.createElement("span");
            label.textContent = `${index + 1}. ${labelFor(id)}`;
            label.style.flex = "1";
            const remove = makeButton("×", `移除 ${id}`);
            remove.onclick = () => {
                selected.splice(index, 1);
                commit();
                render();
            };
            row.ondragstart = (event) => event.dataTransfer.setData("text/plain", String(index));
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

    const load = async () => {
        status.textContent = "正在扫描 Skill…";
        try {
            const response = await api.fetchApi("/qwen_skill_prompt/skills");
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            available = payload.skills || [];
            const known = new Set(available.map((entry) => entry.id));
            selected = selected.filter((id) => known.has(id));
            commit();
            render();
        } catch (error) {
            status.textContent = `加载失败：${error.message}`;
        }
    };

    search.oninput = render;
    refresh.onclick = load;
    upload.onclick = () => fileInput.click();
    fileInput.onchange = async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        const form = new FormData();
        form.append("file", file, file.name);
        status.textContent = `正在上传 ${file.name}…`;
        try {
            const response = await api.fetchApi("/qwen_skill_prompt/upload", { method: "POST", body: form });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            selected.push(payload.id);
            await load();
        } catch (error) {
            status.textContent = `上传失败：${error.message}`;
        } finally {
            fileInput.value = "";
        }
    };

    node.addDOMWidget("skill_picker", "Skill 联合选择", root, { serialize: false });
    render();
    load();
}

app.registerExtension({
    name: "qwen.multi_skill_prompt",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const original = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = original?.apply(this, arguments);
            const skills = this.widgets?.find((widget) => widget.name === "skills");
            const backend = this.widgets?.find((widget) => widget.name === "backend");
            if (skills) installSkillPicker(this, skills);
            if (backend) {
                const callback = backend.callback;
                backend.callback = (...args) => {
                    callback?.apply(backend, args);
                    syncBackendWidgets(this);
                };
            }
            syncBackendWidgets(this);
            return result;
        };
    },
});

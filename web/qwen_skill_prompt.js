import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
    VISIBLE_BACKEND_CHOICES,
    WIDGET_LABELS,
    extractPromptFromExecutedMessage,
    isWidgetVisible,
    normalizeMode,
    setCbkkNodeSource,
} from "./qwen_skill_prompt_ui.mjs";

const NODE_NAME = "QwenMultiSkillPromptGenerator";
const PREVIEW_NODE_NAME = "QwenSkillPromptPreview";

function setWidgetVisible(node, widget, visible) {
    if (!widget) return;
    if (!widget.__cbkkOriginalComputeSize) {
        widget.__cbkkOriginalComputeSize = widget.computeSize?.bind(widget);
    }
    widget.hidden = !visible;
    widget.computeSize = visible
        ? widget.__cbkkOriginalComputeSize
        : () => [0, -4];
    node?.setDirtyCanvas?.(true, true);
}

function localizeWidgets(node) {
    for (const widget of node?.widgets || []) {
        if (widget?.name && WIDGET_LABELS[widget.name]) {
            widget.label = WIDGET_LABELS[widget.name];
        }
    }
}

function syncModeWidgets(node) {
    if (!node?.widgets) return;
    const backend = node.widgets.find((w) => w.name === "backend");
    const localModel = node.widgets.find((w) => w.name === "local_model");
    const mode = normalizeMode(backend?.value);

    for (const widget of node.widgets) {
        if (!widget?.name) continue;
        if (
            widget.name === "skills" ||
            widget.name.startsWith("cbkk_") ||
            widget.name.includes("Skill")
        ) {
            continue;
        }
        setWidgetVisible(
            node,
            widget,
            isWidgetVisible(widget.name, mode, localModel?.value),
        );
    }

    const computed = node.computeSize ? node.computeSize() : [400, 620];
    const targetW = Math.max(node.size?.[0] || 0, computed[0] || 0, 420);
    const targetH = Math.max(node.size?.[1] || 0, computed[1] || 0, 620);
    node.setSize?.([targetW, targetH]);
    node.setDirtyCanvas?.(true, true);
}

function parseSelection(widget) {
    try {
        const parsed = JSON.parse(widget?.value || "[]");
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
    button.title = title || "";
    button.draggable = false;
    button.style.cssText = [
        "padding:6px 10px",
        "border:1px solid #58736a",
        "border-radius:5px",
        `background:${primary ? "#26745f" : "#2d3431"}`,
        "color:#f2f5f4",
        "cursor:pointer",
        "font-weight:600",
        "user-select:none",
    ].join(";");
    button.addEventListener("pointerdown", (e) => e.stopPropagation());
    button.addEventListener("mousedown", (e) => e.stopPropagation());
    return button;
}

async function fetchSkills() {
    const response = await api.fetchApi("/qwen_skill_prompt/skills");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload.skills || [];
}

async function uploadSkill(file, overwrite = false) {
    const form = new FormData();
    form.append("file", file, file.name);
    const url = overwrite
        ? "/qwen_skill_prompt/upload?overwrite=true"
        : "/qwen_skill_prompt/upload";
    const response = await api.fetchApi(url, {
        method: "POST",
        body: form,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
}

async function deleteSkill(skillId) {
    const response = await api.fetchApi("/qwen_skill_prompt/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: skillId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
}

function ensureFileInput() {
    let input = document.getElementById("cbkk-skill-file-input");
    if (!input) {
        input = document.createElement("input");
        input.id = "cbkk-skill-file-input";
        input.type = "file";
        input.accept = ".md,.txt,text/plain,text/markdown";
        input.style.display = "none";
        document.body.appendChild(input);
    }
    return input;
}

function installSkillPicker(node, widget) {
    if (node.__cbkkSkillPickerInstalled) {
        node.__cbkkReloadSkills?.();
        return;
    }
    node.__cbkkSkillPickerInstalled = true;

    let available = [];
    let selected = parseSelection(widget);
    let status = null;
    let render = () => {};

    const commit = () => {
        widget.value = JSON.stringify(selected);
        widget.callback?.(widget.value);
        node.setDirtyCanvas?.(true, true);
    };

    const load = async () => {
        if (status) status.textContent = "正在扫描 Skill…";
        try {
            available = await fetchSkills();
            const known = new Set(available.map((entry) => entry.id));
            selected = selected.filter((id) => known.has(id));
            commit();
            render();
            if (status) status.textContent = `已扫描到 ${available.length} 个 Skill，已选 ${selected.length} 个`;
        } catch (error) {
            const msg = `Skill 加载失败：${error.message}`;
            if (status) status.textContent = msg;
            else console.warn("[cbkk]", msg);
        }
    };
    node.__cbkkReloadSkills = load;

    const fileInput = ensureFileInput();

    const handleUpload = () => {
        fileInput.onchange = async () => {
            const file = fileInput.files?.[0];
            if (!file) return;

            let overwrite = false;
            const existing = available.find(
                (entry) =>
                    entry.source === "user" &&
                    entry.relative_path.toLowerCase() === file.name.toLowerCase()
            );
            if (existing) {
                if (
                    !confirm(
                        `Skill "${file.name}" 已经存在。\n\n点击【确定】将覆盖更新为新文件的内容；\n点击【取消】将放弃本次上传。`
                    )
                ) {
                    fileInput.value = "";
                    return;
                }
                overwrite = true;
            }

            if (status) status.textContent = `正在上传 ${file.name}…`;
            try {
                const entry = await uploadSkill(file, overwrite);
                if (!selected.includes(entry.id)) selected.push(entry.id);
                await load();
                if (status)
                    status.textContent = `${overwrite ? "覆盖更新成功" : "上传成功"}并已加入已选：${entry.id}`;
            } catch (error) {
                const msg = `Skill 上传失败：${error.message}`;
                if (status) status.textContent = msg;
                alert(msg);
            } finally {
                fileInput.value = "";
            }
        };
        fileInput.click();
    };



    // 如果不支持 DOMWidget，提供友好标签并直接返回
    if (typeof node.addDOMWidget !== "function") {
        widget.label = "已选 Skill（JSON 格式；可通过上方按钮上传）";
        load();
        return;
    }

    // 2. 构建富交互 DOM 选择面板
    setWidgetVisible(node, widget, false);

    const root = document.createElement("div");
    root.style.cssText = [
        "display:flex",
        "flex-direction:column",
        "gap:7px",
        "padding:8px",
        "background:#202725",
        "color:#e5ebe8",
        "font:12px sans-serif",
        "border:1px solid #3f514b",
        "border-radius:6px",
        "min-height:240px",
        "--comfy-widget-min-height:240px",
    ].join(";");

    const heading = document.createElement("div");
    heading.textContent = "Skill 联合选择（不限数量，可拖拽排序）";
    heading.style.cssText = "font-weight:700;color:#d8eee7";

    const toolbar = document.createElement("div");
    toolbar.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";

    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "搜索 Skill…";
    search.style.cssText = "flex:1;min-width:120px;background:#151918;color:#eee;border:1px solid #4a5551;border-radius:4px;padding:6px";
    search.addEventListener("pointerdown", (e) => e.stopPropagation());
    search.addEventListener("mousedown", (e) => e.stopPropagation());

    const refreshBtn = makeButton("↻ 刷新", "重新扫描 Skill 目录");
    const uploadBtn = makeButton("⬆ 上传 Skill", "上传 UTF-8 编码的 .md 或 .txt 文件", true);
    refreshBtn.onclick = () => load();
    uploadBtn.onclick = handleUpload;
    toolbar.append(search, uploadBtn, refreshBtn);

    const columns = document.createElement("div");
    columns.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:7px;min-height:140px";

    const choices = document.createElement("div");
    const chosen = document.createElement("div");
    for (const [element, title] of [
        [choices, "可选 Skill（点击添加）"],
        [chosen, "已选 Skill（拖拽排序）"],
    ]) {
        element.style.cssText = "overflow:auto;max-height:230px;padding:6px;border:1px solid #3f4945;border-radius:4px;background:#171b1a";
    }
    columns.append(choices, chosen);

    status = document.createElement("div");
    status.style.cssText = "min-height:16px;color:#a9bbb4;font-size:11px";
    root.append(heading, toolbar, columns, status);

    const labelFor = (id) =>
        available.find((entry) => entry.id === id)?.relative_path || id;

    render = () => {
        choices.replaceChildren();
        chosen.replaceChildren();

        const choicesHeader = document.createElement("div");
        choicesHeader.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px";
        const choicesTitle = document.createElement("span");
        choicesTitle.textContent = "可选 Skill（点击添加）";
        choicesTitle.style.cssText = "font-weight:700;color:#bcd2ca";
        choicesHeader.append(choicesTitle);
        choices.append(choicesHeader);

        const chosenHeader = document.createElement("div");
        chosenHeader.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px";
        const chosenTitle = document.createElement("span");
        chosenTitle.textContent = `已选 Skill (${selected.length})`;
        chosenTitle.style.cssText = "font-weight:700;color:#bcd2ca";

        const clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.textContent = "清空全部";
        clearBtn.title = "清空当前节点中已选的所有 Skill";
        clearBtn.draggable = false;
        clearBtn.style.cssText = "padding:2px 7px;font-size:11px;background:#4a2b2b;color:#ffcccc;border:1px solid #663d3d;border-radius:3px;cursor:pointer";
        clearBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
        clearBtn.addEventListener("mousedown", (e) => e.stopPropagation());
        clearBtn.onclick = (e) => {
            e.stopPropagation();
            if (selected.length === 0) return;
            selected = [];
            commit();
            render();
        };
        chosenHeader.append(chosenTitle, clearBtn);
        chosen.append(chosenHeader);

        const query = search.value.trim().toLocaleLowerCase();
        for (const entry of available) {
            if (
                selected.includes(entry.id) ||
                (query && !entry.id.toLocaleLowerCase().includes(query))
            ) {
                continue;
            }
            const itemRow = document.createElement("div");
            itemRow.style.cssText = "display:flex;align-items:center;gap:4px;margin-bottom:4px";

            const addBtn = makeButton(
                `+ ${entry.source === "user" ? "用户" : "内置"}：${entry.relative_path}`,
                `添加 ${entry.id} 到节点`,
            );
            addBtn.style.flex = "1";
            addBtn.style.textAlign = "left";
            addBtn.style.overflow = "hidden";
            addBtn.style.textOverflow = "ellipsis";
            addBtn.style.whiteSpace = "nowrap";
            addBtn.onclick = (e) => {
                e.stopPropagation();
                if (!selected.includes(entry.id)) {
                    selected.push(entry.id);
                    commit();
                    render();
                }
            };
            itemRow.append(addBtn);

            if (entry.source === "user") {
                const delBtn = document.createElement("button");
                delBtn.type = "button";
                delBtn.textContent = "🗑️";
                delBtn.title = `从磁盘永久删除用户 Skill: ${entry.relative_path}`;
                delBtn.draggable = false;
                delBtn.style.cssText = "padding:4px 6px;background:#442222;color:#ff9999;border:1px solid #663333;border-radius:4px;cursor:pointer;flex-shrink:0";
                delBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
                delBtn.addEventListener("mousedown", (e) => e.stopPropagation());
                delBtn.onclick = async (e) => {
                    e.stopPropagation();
                    if (!confirm(`确定要彻底删除用户 Skill 文件 "${entry.relative_path}" 吗？此操作无法撤销。`)) {
                        return;
                    }
                    try {
                        if (status) status.textContent = `正在删除 ${entry.relative_path}…`;
                        await deleteSkill(entry.id);
                        const selIdx = selected.indexOf(entry.id);
                        if (selIdx !== -1) {
                            selected.splice(selIdx, 1);
                        }
                        await load();
                        if (status) status.textContent = `已成功删除 Skill: ${entry.relative_path}`;
                    } catch (err) {
                        const msg = `删除失败: ${err.message}`;
                        if (status) status.textContent = msg;
                        alert(msg);
                    }
                };
                itemRow.append(delBtn);
            }
            choices.append(itemRow);
        }

        selected.forEach((id, index) => {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:6px;margin-bottom:4px;padding:4px 6px;background:#29322f;border-radius:4px;border:1px solid #3c4944";

            const handle = document.createElement("span");
            handle.textContent = "☰";
            handle.title = "按住拖拽排序";
            handle.draggable = true;
            handle.style.cssText = "cursor:grab;user-select:none;padding:0 3px;color:#8ba59b;font-weight:bold";

            const label = document.createElement("span");
            label.textContent = `${index + 1}. ${labelFor(id)}`;
            label.title = `${id} (双击可快速移除)`;
            label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;user-select:none;cursor:pointer";

            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "× 移除";
            remove.title = `从节点中移除: ${id}`;
            remove.draggable = false;
            remove.style.cssText = "padding:3px 8px;border:1px solid #853e3e;border-radius:4px;background:#5e2a2a;color:#ffdede;cursor:pointer;font-size:11px;font-weight:600;user-select:none;white-space:nowrap;flex-shrink:0";
            remove.addEventListener("pointerdown", (e) => e.stopPropagation());
            remove.addEventListener("mousedown", (e) => e.stopPropagation());
            remove.onclick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                const targetIdx = selected.indexOf(id);
                if (targetIdx !== -1) {
                    selected.splice(targetIdx, 1);
                }
                commit();
                render();
            };

            row.ondblclick = (e) => {
                e.stopPropagation();
                const targetIdx = selected.indexOf(id);
                if (targetIdx !== -1) {
                    selected.splice(targetIdx, 1);
                }
                commit();
                render();
            };

            row.draggable = true;
            row.ondragstart = (event) => {
                event.dataTransfer.setData("text/plain", String(index));
                event.dataTransfer.effectAllowed = "move";
            };
            row.ondragover = (event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
            };
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

        status.textContent = `已选择 ${selected.length} 个 Skill（双击或点击「× 移除」删除）`;
    };

    search.oninput = render;

    try {
        const domWidget = node.addDOMWidget("cbkk_skill_picker", "customwidget", root, {
            serialize: false,
            getMinHeight: () => 240,
            computeSize: () => [node.size?.[0] || 420, 240],
        });
        if (domWidget) {
            domWidget.serialize = false;
        }
    } catch (error) {
        setWidgetVisible(node, widget, true);
        widget.label = "Skill 选择（JSON；可通过上方按钮上传）";
        console.warn("[cbkk] DOMWidget 挂载失败，启用兼容模式", error);
        load();
        return;
    }

    render();
    load();
}

function spawnConnectedClipNode(sourceNode, btn) {
    if (!globalThis.LiteGraph || !app.graph) return;
    const targetName = "CLIPTextEncode";
    const targetNode = LiteGraph.createNode(targetName);
    if (!targetNode) {
        alert("未找到 CLIPTextEncode 节点类型");
        return;
    }

    targetNode.pos = [
        sourceNode.pos[0] + sourceNode.size[0] + 50,
        sourceNode.pos[1] + Math.max(0, sourceNode.size[1] - 220),
    ];
    app.graph.add(targetNode);

    const textWidget = targetNode.widgets?.find((w) => w.name === "text");
    if (textWidget) {
        if (typeof targetNode.convertWidgetToInput === "function") {
            targetNode.convertWidgetToInput(textWidget);
        }
    }

    const textInputIdx = targetNode.inputs?.findIndex((input) => input.name === "text");
    if (textInputIdx !== -1) {
        sourceNode.connect(0, targetNode, textInputIdx);
    }

    app.canvas?.selectNode(targetNode, false);
    app.graph.setDirtyCanvas(true, true);

    if (btn) {
        const oldText = btn.textContent;
        btn.textContent = "✓ 已引出并连接!";
        btn.style.background = "#2a5d7c";
        btn.style.borderColor = "#4c8db8";
        setTimeout(() => {
            btn.textContent = oldText;
            btn.style.background = "#1d3547";
            btn.style.borderColor = "#36536b";
        }, 1600);
    }
}

function pickTargetAndFillPrompt(promptText, btn) {
    const textToFill = (typeof promptText === "string" ? promptText : "").trim();
    if (!textToFill) {
        alert("当前暂无可填入的提示词内容，请先生成或输入提示词。");
        return;
    }
    if (btn) {
        btn.textContent = "👆 点击目标节点...";
        btn.style.background = "#6b4919";
        btn.style.borderColor = "#c48831";
    }

    const handler = (e) => {
        if (btn) {
            btn.textContent = "🎯 填入文本框";
            btn.style.background = "#283337";
            btn.style.borderColor = "#485459";
        }
        window.removeEventListener("pointerdown", handler, true);

        const canvas = app.canvas;
        if (!canvas || !app.graph) return;
        const pos = canvas.convertEventToCanvasOffset(e);
        const targetNode = app.graph.getNodeOnPos(pos[0], pos[1]);
        if (!targetNode) return;

        const textWidget = targetNode.widgets?.find(
            (w) => w.name === "text" || w.name === "prompt" || w.name === "positive" || (typeof w.value === "string" && w.type === "customtext")
        ) || targetNode.widgets?.find((w) => typeof w.value === "string");

        if (textWidget) {
            textWidget.value = textToFill;
            textWidget.callback?.(textToFill);
            targetNode.setDirtyCanvas?.(true, true);
            app.graph.setDirtyCanvas(true, true);
            if (btn) {
                btn.textContent = "✓ 已填入目标文本框!";
                btn.style.background = "#2e7d58";
                setTimeout(() => {
                    btn.textContent = "🎯 填入文本框";
                    btn.style.background = "#283337";
                }, 1500);
            }
        } else {
            alert(`节点「${targetNode.title || targetNode.type}」中未找到可填入的文本框。`);
        }
    };

    setTimeout(() => {
        window.addEventListener("pointerdown", handler, { capture: true, once: true });
    }, 60);
}

function installPromptPreview(node, customTitle = "✨ 生成提示词预览") {
    if (node.__cbkkPromptPreviewInstalled) return;
    node.__cbkkPromptPreviewInstalled = true;

    if (typeof node.addDOMWidget !== "function") return;

    const wrap = document.createElement("div");
    wrap.style.cssText = [
        "display:flex",
        "flex-direction:column",
        "gap:6px",
        "padding:8px",
        "background:#1b2220",
        "color:#e5ebe8",
        "font:12px sans-serif",
        "border:1px solid #384843",
        "border-radius:6px",
        "box-sizing:border-box",
        "width:100%",
        "min-height:140px",
        "--comfy-widget-min-height:140px",
    ].join(";");

    const header = document.createElement("div");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;user-select:none;flex-wrap:wrap;gap:4px";

    const titleBox = document.createElement("div");
    titleBox.style.cssText = "display:flex;align-items:center;gap:6px";

    const title = document.createElement("span");
    title.textContent = customTitle;
    title.style.cssText = "font-weight:700;color:#cde5dc;font-size:12px";

    const countBadge = document.createElement("span");
    countBadge.style.cssText = "font-size:11px;color:#8ba59c;margin-left:4px";
    countBadge.textContent = "";

    titleBox.append(title, countBadge);

    const btnGroup = document.createElement("div");
    btnGroup.style.cssText = "display:flex;gap:4px;flex-wrap:wrap";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.textContent = "📋 复制";
    copyBtn.title = "点击复制生成的完整提示词到剪贴板";
    copyBtn.draggable = false;
    copyBtn.style.cssText = [
        "padding:3px 7px",
        "border:1px solid #3c6e5f",
        "border-radius:4px",
        "background:#205043",
        "color:#d4f5ec",
        "cursor:pointer",
        "font-size:11px",
        "font-weight:600",
        "user-select:none",
        "white-space:nowrap",
        "transition:all 0.2s ease",
    ].join(";");
    copyBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
    copyBtn.addEventListener("mousedown", (e) => e.stopPropagation());

    const spawnBtn = document.createElement("button");
    spawnBtn.type = "button";
    spawnBtn.textContent = "🔗 引出文本节点";
    spawnBtn.title = "在右侧自动创建 CLIP 文本编码器，并将文本框自动转换为输入后与当前提示词相连";
    spawnBtn.draggable = false;
    spawnBtn.style.cssText = [
        "padding:3px 7px",
        "border:1px solid #36536b",
        "border-radius:4px",
        "background:#1d3547",
        "color:#d2e7f7",
        "cursor:pointer",
        "font-size:11px",
        "font-weight:600",
        "user-select:none",
        "white-space:nowrap",
        "transition:all 0.2s ease",
    ].join(";");
    spawnBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
    spawnBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    spawnBtn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        spawnConnectedClipNode(node, spawnBtn);
    };

    const fillBtn = document.createElement("button");
    fillBtn.type = "button";
    fillBtn.textContent = "🎯 填入文本框";
    fillBtn.title = "点击后，直接在画布上点击任意节点的文本框（如已有的 CLIPTextEncode），即可将提示词填入";
    fillBtn.draggable = false;
    fillBtn.style.cssText = [
        "padding:3px 7px",
        "border:1px solid #485459",
        "border-radius:4px",
        "background:#283337",
        "color:#cfdcde",
        "cursor:pointer",
        "font-size:11px",
        "user-select:none",
        "white-space:nowrap",
        "transition:all 0.2s ease",
    ].join(";");
    fillBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
    fillBtn.addEventListener("mousedown", (e) => e.stopPropagation());
    fillBtn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        pickTargetAndFillPrompt(textarea.value, fillBtn);
    };

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "清空";
    clearBtn.title = "清空当前预览内容";
    clearBtn.draggable = false;
    clearBtn.style.cssText = [
        "padding:3px 7px",
        "border:1px solid #4a5853",
        "border-radius:4px",
        "background:#28322f",
        "color:#b5c4bf",
        "cursor:pointer",
        "font-size:11px",
        "user-select:none",
        "white-space:nowrap",
    ].join(";");
    clearBtn.addEventListener("pointerdown", (e) => e.stopPropagation());
    clearBtn.addEventListener("mousedown", (e) => e.stopPropagation());

    btnGroup.append(copyBtn, spawnBtn, fillBtn, clearBtn);
    header.append(titleBox, btnGroup);

    const textarea = document.createElement("textarea");
    textarea.readOnly = true;
    textarea.placeholder = "尚未执行生成。运行工作流后，生成的提示词将在此处直接展示并支持一键复制。";
    textarea.style.cssText = [
        "width:100%",
        "height:100px",
        "min-height:90px",
        "max-height:300px",
        "box-sizing:border-box",
        "resize:vertical",
        "background:#121716",
        "color:#ebf3f0",
        "border:1px solid #2e3d38",
        "border-radius:4px",
        "padding:8px",
        "font-family:Consolas, Monaco, 'Lucida Console', monospace, system-ui, sans-serif",
        "font-size:12px",
        "line-height:1.5",
        "outline:none",
        "overflow-y:auto",
        "white-space:pre-wrap",
        "word-break:break-word",
        "user-select:text",
    ].join(";");

    textarea.addEventListener("pointerdown", (e) => e.stopPropagation());
    textarea.addEventListener("mousedown", (e) => e.stopPropagation());
    textarea.addEventListener("wheel", (e) => e.stopPropagation());

    wrap.append(header, textarea);

    const updateDisplay = (text) => {
        const clean = typeof text === "string" ? text : "";
        textarea.value = clean;
        if (clean) {
            countBadge.textContent = `(${clean.length} 字符)`;
        } else {
            countBadge.textContent = "";
        }
        node.setDirtyCanvas?.(true, true);
    };

    copyBtn.onclick = async (e) => {
        e.stopPropagation();
        e.preventDefault();
        const content = textarea.value;
        if (!content) return;
        let success = false;
        try {
            if (navigator?.clipboard?.writeText) {
                await navigator.clipboard.writeText(content);
                success = true;
            }
        } catch {
            success = false;
        }
        if (!success) {
            try {
                textarea.select();
                success = document.execCommand("copy");
                window.getSelection()?.removeAllRanges();
            } catch {
                success = false;
            }
        }
        if (success) {
            const oldText = copyBtn.textContent;
            copyBtn.textContent = "✓ 已复制!";
            copyBtn.style.background = "#2e7d58";
            copyBtn.style.borderColor = "#44b27f";
            setTimeout(() => {
                copyBtn.textContent = oldText;
                copyBtn.style.background = "#205043";
                copyBtn.style.borderColor = "#3c6e5f";
            }, 1500);
        } else {
            alert("复制失败，请手动在文本框中全选复制。");
        }
    };

    clearBtn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        if (!node.properties) node.properties = {};
        node.properties["cbkk_last_prompt"] = "";
        updateDisplay("");
    };

    const savedPrompt = node.properties?.["cbkk_last_prompt"] || "";
    if (savedPrompt) {
        updateDisplay(savedPrompt);
    }

    node.__cbkkUpdatePromptPreview = (message) => {
        const text = extractPromptFromExecutedMessage(message);
        if (!node.properties) node.properties = {};
        node.properties["cbkk_last_prompt"] = text || "";
        updateDisplay(text || "");
    };

    try {
        const domWidget = node.addDOMWidget("cbkk_prompt_preview", "customwidget", wrap, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => 140,
            computeSize: () => [node.size?.[0] || 420, 140],
        });
        if (domWidget) {
            domWidget.serialize = false;
        }
    } catch (error) {
        console.warn("[cbkk] Prompt preview DOMWidget 挂载失败", error);
    }
}

function setupNode(node) {
    if (!node || !node.widgets) return;
    localizeWidgets(node);

    const backend = node.widgets.find((w) => w.name === "backend");
    const localModel = node.widgets.find((w) => w.name === "local_model");
    if (backend?.options) {
        backend.options.values = [...VISIBLE_BACKEND_CHOICES];
    }

    for (const widget of [backend, localModel]) {
        if (!widget || widget.__cbkkBound) continue;
        widget.__cbkkBound = true;
        const callback = widget.callback;
        widget.callback = function () {
            callback?.apply(this, arguments);
            syncModeWidgets(node);
        };
    }

    const skills = node.widgets.find((w) => w.name === "skills");
    if (skills) {
        installSkillPicker(node, skills);
    }

    installPromptPreview(node);

    if (!node.__cbkkExecutedHooked) {
        node.__cbkkExecutedHooked = true;
        const originalInstanceExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            const result = originalInstanceExecuted?.apply(this, arguments);
            try {
                node.__cbkkUpdatePromptPreview?.(message);
            } catch (err) {
                console.error("[cbkk] 更新提示词预览失败:", err);
            }
            return result;
        };
    }

    syncModeWidgets(node);
}

function setupPreviewNode(node) {
    if (!node) return;
    if (node.widgets) {
        for (const w of node.widgets) {
            if (w.name === "text") {
                setWidgetVisible(node, w, false);
            }
        }
    }
    installPromptPreview(node, "✨ 提示词展示与中继");

    if (!node.__cbkkExecutedHooked) {
        node.__cbkkExecutedHooked = true;
        const originalInstanceExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            const result = originalInstanceExecuted?.apply(this, arguments);
            try {
                node.__cbkkUpdatePromptPreview?.(message);
            } catch (err) {
                console.error("[cbkk] 更新提示词预览失败:", err);
            }
            return result;
        };
    }

    const targetW = Math.max(node.size?.[0] || 0, 420);
    const targetH = Math.max(node.size?.[1] || 0, 200);
    node.setSize?.([targetW, targetH]);
    node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "cbkk.qwen_multi_skill_prompt.zh_cn",
    addCustomNodeDefs(defs) {
        setCbkkNodeSource(defs);
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name === PREVIEW_NODE_NAME) {
            const originalCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const result = originalCreated?.apply(this, arguments);
                setTimeout(() => setupPreviewNode(this), 10);
                return result;
            };

            const originalConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                const result = originalConfigure?.apply(this, arguments);
                setTimeout(() => setupPreviewNode(this), 10);
                return result;
            };

            const originalExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                const result = originalExecuted?.apply(this, arguments);
                try {
                    this.__cbkkUpdatePromptPreview?.(message);
                } catch (err) {
                    console.error("[cbkk] 更新提示词预览失败:", err);
                }
                return result;
            };
            return;
        }

        if (nodeData?.name !== NODE_NAME) return;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            setTimeout(() => setupNode(this), 10);
            return result;
        };

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigure?.apply(this, arguments);
            setTimeout(() => setupNode(this), 10);
            return result;
        };

        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = originalExecuted?.apply(this, arguments);
            try {
                this.__cbkkUpdatePromptPreview?.(message);
            } catch (err) {
                console.error("[cbkk] 更新提示词预览失败:", err);
            }
            return result;
        };
    },
    nodeCreated(node) {
        if (node?.comfyClass === NODE_NAME) {
            setTimeout(() => setupNode(node), 20);
        } else if (node?.comfyClass === PREVIEW_NODE_NAME) {
            setTimeout(() => setupPreviewNode(node), 20);
        }
    },
    loadedGraphNode(node) {
        if (node?.comfyClass === NODE_NAME) {
            setTimeout(() => setupNode(node), 20);
        } else if (node?.comfyClass === PREVIEW_NODE_NAME) {
            setTimeout(() => setupPreviewNode(node), 20);
        }
    },
});

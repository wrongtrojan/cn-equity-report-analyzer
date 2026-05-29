(function () {
  const theme = window.ReportGraphTheme;
  const dataEl = document.getElementById("report-graph-data");
  const tabBar = document.getElementById("tab-bar");
  const graphContainer = document.getElementById("graph");
  const evidencePanel = document.getElementById("evidence-panel");
  const viewDescription = document.getElementById("view-description");
  const graphLegend = document.getElementById("graph-legend");
  const graphStatus = document.getElementById("graph-status");

  let network = null;
  let activeType = null;
  let payload = null;

  function showFatal(message) {
    graphContainer.innerHTML = `<div class="empty-state">${message}</div>`;
    if (graphStatus) graphStatus.textContent = "加载失败";
  }

  try {
    if (!theme) throw new Error("graph_theme.js 未加载");
    if (!dataEl) throw new Error("缺少 report-graph-data");
    if (typeof vis === "undefined") throw new Error("vis-network 未加载，请检查网络或使用 --serve 访问");
    payload = JSON.parse(dataEl.textContent || "{}");
    if (!payload.views) throw new Error("图谱数据格式无效");
  } catch (err) {
    showFatal(err.message || "图谱初始化失败");
    return;
  }

  const nonEmptyViews = theme.TAB_ORDER.map((type) => payload.views[type]).filter((view) => view && !view.empty);

  function escapeHtml(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderLegend() {
    graphLegend.innerHTML = Object.entries(theme.ENTITY_TYPE_LABELS)
      .map(
        ([type, label]) =>
          `<span class="legend-item"><span class="legend-dot legend-${type}"></span>${label}</span>`
      )
      .join("");
  }

  function renderTabs() {
    tabBar.innerHTML = nonEmptyViews
      .map(
        (view) => `
      <button class="tab-btn" data-type="${view.relation_type}" style="--tab-accent:${theme.relationColor(view.relation_type)}" type="button">
        <span class="tab-label">${escapeHtml(view.label)}</span>
        <span class="tab-count">${view.count}</span>
      </button>`
      )
      .join("");

    tabBar.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchView(btn.dataset.type));
    });
  }

  function renderEmptyEvidence(view) {
    evidencePanel.innerHTML = `
      <div class="panel-placeholder">
        <p class="panel-kicker">${escapeHtml(view.label)}</p>
        <h3>选择关系边</h3>
        <p class="muted">${escapeHtml(view.description || "点击图谱中的关系边查看证据。")}</p>
      </div>`;
  }

  function renderEvidence(edge) {
    if (!edge) {
      renderEmptyEvidence(payload.views[activeType]);
      return;
    }

    const attrs = edge.attrs || {};
    const attrRows = Object.entries(attrs)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(
        ([key, value]) =>
          `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(String(value))}</td></tr>`
      )
      .join("");

    const evidenceHtml = (edge.evidence || []).length
      ? edge.evidence
          .map(
            (item) => `
          <article class="evidence-card">
            <div class="evidence-meta">
              <span class="badge">${escapeHtml(item.evidence_type || "evidence")}</span>
              ${item.section_key ? `<span class="badge badge-muted">${escapeHtml(item.section_key)}</span>` : ""}
              ${item.page_num ? `<span class="badge badge-muted">p.${item.page_num}</span>` : ""}
            </div>
            <p class="evidence-snippet">${escapeHtml(item.snippet || "")}</p>
          </article>`
          )
          .join("")
      : `<p class="muted">无结构化证据。</p>`;

    evidencePanel.innerHTML = `
      <div class="relation-summary">
        <p class="panel-kicker">${escapeHtml(edge.relation_type)}</p>
        <div class="relation-line">
          <strong>${escapeHtml(edge.subject_name)}</strong>
          <span class="relation-arrow">${escapeHtml(edge.label)}</span>
          <strong>${escapeHtml(edge.object_name)}</strong>
        </div>
        <p class="muted">来源 ${escapeHtml(edge.source || "rule")} · 置信度 ${edge.confidence ?? 1}${
          edge.merged_count ? ` · 合并 ${edge.merged_count} 条关系` : ""
        }</p>
      </div>
      ${attrRows ? `<table class="attr-table"><tbody>${attrRows}</tbody></table>` : ""}
      <div class="evidence-list">${evidenceHtml}</div>`;
  }

  function destroyNetwork() {
    if (network) {
      network.destroy();
      network = null;
    }
  }

  function switchView(relationType, pushHash = true) {
    const view = payload.views[relationType];
    if (!view || view.empty) return;

    activeType = relationType;
    tabBar.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.type === relationType);
    });

    viewDescription.textContent = view.description || "";
    if (graphStatus) {
      graphStatus.textContent = `${view.label} · ${view.count} 条关系 · ${view.nodes.length} 个节点`;
    }
    renderEmptyEvidence(view);

    destroyNetwork();

    const nodeItems = view.nodes.map((node) => theme.buildNodeVis(node));
    const edgeItems = theme.spreadParallelEdges(
      view.edges.map((edge) => theme.buildEdgeVis(edge, relationType))
    );
    const laidOutNodes = theme.layoutNodes(relationType, nodeItems, edgeItems);

    const nodes = new vis.DataSet(laidOutNodes);
    const edges = new vis.DataSet(edgeItems);
    network = new vis.Network(graphContainer, { nodes, edges }, theme.getNetworkOptions());

    const fitGraph = () => {
      network.fit({ padding: 64, animation: { duration: 280, easingFunction: "easeInOutQuad" } });
      network.off("afterDrawing", fitGraph);
    };
    network.on("afterDrawing", fitGraph);

    network.on("selectEdge", (params) => {
      if (!params.edges.length) return;
      const edge = edges.get(params.edges[0]);
      renderEvidence(edge.data);
    });
    network.on("deselectEdge", () => renderEvidence(null));

    if (pushHash) {
      history.replaceState(null, "", `#${relationType}`);
    }
  }

  function initialTab() {
    const hash = location.hash.replace(/^#/, "");
    if (hash && payload.views[hash] && !payload.views[hash].empty) {
      return hash;
    }
    return nonEmptyViews[0]?.relation_type || null;
  }

  if (!nonEmptyViews.length) {
    tabBar.innerHTML = `<p class="muted">暂无可展示的关系数据。</p>`;
    showFatal("未找到关系边，请先运行 ingest --with-relations。");
    evidencePanel.innerHTML = `<p class="muted">无关系数据。</p>`;
    return;
  }

  renderLegend();
  renderTabs();
  switchView(initialTab(), false);
})();

(function (global) {
  const ENTITY_COLORS = {
    company: {
      background: "#0f172a",
      border: "#0f172a",
      highlight: { background: "#1e293b", border: "#0f172a" },
    },
    person: {
      background: "#fef3c7",
      border: "#f59e0b",
      highlight: { background: "#fde68a", border: "#d97706" },
    },
    organization: {
      background: "#dcfce7",
      border: "#16a34a",
      highlight: { background: "#bbf7d0", border: "#15803d" },
    },
    subsidiary: {
      background: "#e0e7ff",
      border: "#4f46e5",
      highlight: { background: "#c7d2fe", border: "#3730a3" },
    },
  };

  const RELATION_COLORS = {
    shareholder_of: "#2563eb",
    actual_controller_of: "#4f46e5",
    executive_of: "#0284c7",
    director_of: "#0f766e",
    subsidiary_of: "#7c3aed",
    invest_in: "#4338ca",
    related_party_of: "#be123c",
    transaction_with: "#b45309",
  };

  const ENTITY_TYPE_LABELS = {
    company: "公司",
    person: "自然人",
    organization: "机构",
    subsidiary: "子公司",
  };

  const TAB_ORDER = [
    "shareholder_of",
    "actual_controller_of",
    "executive_of",
    "director_of",
    "subsidiary_of",
    "invest_in",
    "related_party_of",
    "transaction_with",
  ];

  function relationColor(relationType) {
    return RELATION_COLORS[relationType] || "#64748b";
  }

  function withAlpha(hex, alpha) {
    const raw = (hex || "").replace("#", "");
    if (raw.length !== 6) return `rgba(100,116,139,${alpha})`;
    const r = parseInt(raw.slice(0, 2), 16);
    const g = parseInt(raw.slice(2, 4), 16);
    const b = parseInt(raw.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  function truncateLabel(text, maxLen) {
    const value = String(text || "");
    return value.length > maxLen ? `${value.slice(0, maxLen - 1)}…` : value;
  }

  function buildNodeVis(node) {
    const palette = ENTITY_COLORS[node.entity_type] || ENTITY_COLORS.organization;
    const isCompany = node.entity_type === "company";
    return {
      id: node.id,
      label: truncateLabel(node.label, isCompany ? 18 : 10),
      title: `${ENTITY_TYPE_LABELS[node.entity_type] || node.entity_type}\n${node.label}`,
      shape: isCompany ? "box" : "dot",
      size: isCompany ? 26 : 14,
      color: palette,
      font: {
        size: isCompany ? 13 : 11,
        color: isCompany ? "#ffffff" : "#334155",
        face: "Inter, Noto Sans SC, sans-serif",
        bold: isCompany,
      },
      borderWidth: isCompany ? 0 : 1.5,
      margin: 10,
      data: node,
    };
  }

  function buildEdgeVis(edge, relationType) {
    const color = relationColor(relationType);
    const label = truncateLabel(edge.label, 16);
    return {
      id: edge.id,
      from: edge.from_id,
      to: edge.to_id,
      label: label || "",
      title: `${edge.subject_name} → ${edge.object_name}`,
      arrows: { to: { enabled: true, scaleFactor: 0.55 } },
      color: {
        color: withAlpha(color, 0.38),
        highlight: color,
        hover: color,
        opacity: 0.95,
      },
      font: {
        size: 10,
        color: withAlpha(color, 0.92),
        strokeWidth: 0,
        face: "Inter, Noto Sans SC, sans-serif",
        align: "horizontal",
      },
      width: 1,
      smooth: { type: "cubicBezier", forceDirection: "vertical", roundness: 0.2 },
      data: edge,
    };
  }

  function applyStarLayout(nodes, edges, companyNodeId) {
    if (!companyNodeId) return nodes;
    const others = nodes.filter((n) => n.id !== companyNodeId);
    const radius = Math.max(220, Math.min(420, others.length * 36));
    return nodes.map((node) => {
      if (node.id === companyNodeId) {
        return { ...node, x: 0, y: 0, fixed: true };
      }
      const idx = others.findIndex((n) => n.id === node.id);
      const angle = (2 * Math.PI * idx) / Math.max(others.length, 1) - Math.PI / 2;
      return {
        ...node,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        fixed: true,
      };
    });
  }

  function applyHierarchyLayout(nodes, edges, companyNodeId, relationType) {
    if (!companyNodeId) return nodes;
    const childIds = new Set();
    for (const edge of edges) {
      if (relationType === "subsidiary_of" && edge.to === companyNodeId) {
        childIds.add(edge.from);
      } else if (edge.from === companyNodeId) {
        childIds.add(edge.to);
      }
    }
    const children = nodes.filter((n) => childIds.has(n.id));
    const spread = Math.max(180, children.length * 140);
    return nodes.map((node) => {
      if (node.id === companyNodeId) {
        return { ...node, x: 0, y: -100, fixed: true };
      }
      const idx = children.findIndex((n) => n.id === node.id);
      if (idx >= 0) {
        const x = (idx - (children.length - 1) / 2) * (spread / Math.max(children.length, 1));
        return { ...node, x, y: 110, fixed: true };
      }
      return { ...node, fixed: true };
    });
  }

  function findCompanyNodeId(nodes) {
    const company = nodes.find((n) => n.data?.entity_type === "company");
    return company ? company.id : null;
  }

  function getNetworkOptions() {
    return {
      autoResize: true,
      physics: { enabled: false },
      interaction: {
        hover: true,
        tooltipDelay: 80,
        multiselect: false,
        selectConnectedEdges: false,
        zoomView: true,
        dragView: true,
      },
      edges: {
        selectionWidth: 0.5,
        chosen: {
          edge: (values, _id, _selected, hovering) => {
            values.width = hovering ? 2 : 1;
          },
        },
      },
      nodes: {
        shadow: false,
      },
    };
  }

  function layoutNodes(relationType, nodeItems, edgeItems) {
    const companyNodeId = findCompanyNodeId(nodeItems);
    if (relationType === "subsidiary_of" || relationType === "invest_in") {
      return applyHierarchyLayout(nodeItems, edgeItems, companyNodeId, relationType);
    }
    return applyStarLayout(nodeItems, edgeItems, companyNodeId);
  }

  global.ReportGraphTheme = {
    TAB_ORDER,
    ENTITY_TYPE_LABELS,
    relationColor,
    buildNodeVis,
    buildEdgeVis,
    getNetworkOptions,
    layoutNodes,
  };
})(window);

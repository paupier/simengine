// kg-graph.js — hand-rolled layered SVG renderer for the knowledge graph
// (View mode). No external libraries (design decision: see
// docs/superpowers/specs/2026-07-20-visual-plant-model-editor-design.md).
//
// Layout, fixed rows top to bottom:
//   1. Breadcrumb (Enterprise > Site > Area > Line), compact text strip
//   2. Flow row: Source -> Station -> Buffer -> Station -> ... -> Sink
//   3. Per-station sub-entity row: ProcessValue / FailureMode / CycleStopReason
//      (Metric nodes only when showMetrics is on)
//   4. Shared alarm-code band at the bottom; every station's CAN_RAISE edges
//      curve down into it.
(function () {
  const LANE_W = 200;
  const STATION_H = 60;
  const STATION_W = 140;
  const BUF_W = 50;
  const SUBROW_H = 46;
  const SUB_W = 150;
  const ROW_GAP = 26;

  function svgEl(tag, attrs, text) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function healthLabel(node) {
    if (node.health_h_max == null) return null;
    const cbm = node.health_cbm_threshold != null && node.health_cbm_threshold < node.health_h_max;
    return "h " + node.health_h_max + " · " + (cbm ? "CBM" : "RTF");
  }

  function stationLine2(node) {
    if (node.cycle_time != null) return Number(node.cycle_time).toFixed(1) + "s";
    if (node.target_ppm != null) return node.target_ppm + " ppm";
    return "";
  }

  function subEntityLabel(node) {
    if (node.type === "ProcessValue") {
      const lim = node.alarm_high != null ? ("≤" + node.alarm_high)
        : node.alarm_low != null ? ("≥" + node.alarm_low) : "";
      return { type: "pv · " + node.unit, main: (node.name + " " + lim).trim() };
    }
    if (node.type === "FailureMode") {
      return { type: "failure · " + node.failure_type, main: node.name };
    }
    if (node.type === "CycleStopReason") {
      return { type: "cycle stop", main: node.name };
    }
    if (node.type === "Metric") {
      return { type: "metric", main: node.name };
    }
    return { type: node.type.toLowerCase(), main: node.name };
  }

  function alarmEdgeClass(codeName) {
    if (codeName.indexOf("FM_") === 0) return "kg-edge-failuremode";
    if (codeName.indexOf("PV_") === 0) return "kg-edge-processvalue";
    if (codeName.indexOf("CS_") === 0) return "kg-edge-cyclestopreason";
    return "kg-edge-alarm";
  }

  function renderKGGraph(container, nodeLink, opts) {
    opts = opts || {};
    const showMetrics = !!opts.showMetrics;
    const onNodeClick = opts.onNodeClick || function () {};

    const nodes = nodeLink.nodes || [];
    const edges = nodeLink.edges || [];
    const byId = {};
    nodes.forEach(function (n) { byId[n.id] = n; });

    const stations = nodes.filter(function (n) { return n.type === "Station"; });
    const buffers = nodes.filter(function (n) { return n.type === "Buffer"; });
    const line = nodes.filter(function (n) { return n.type === "Line"; })[0];
    const area = nodes.filter(function (n) { return n.type === "Area"; })[0];
    const site = nodes.filter(function (n) { return n.type === "Site"; })[0];
    const enterprise = nodes.filter(function (n) { return n.type === "Enterprise"; })[0];
    const alarmCodes = nodes.filter(function (n) { return n.type === "AlarmCode"; });

    const subTypes = showMetrics
      ? ["ProcessValue", "FailureMode", "CycleStopReason", "Metric"]
      : ["ProcessValue", "FailureMode", "CycleStopReason"];

    const breadcrumbY = 20;
    const flowY = 70;
    const subY = flowY + STATION_H + ROW_GAP;
    const laneX = function (i) { return 60 + i * LANE_W; };

    const laneSubs = stations.map(function (st) {
      return nodes.filter(function (n) {
        return n.station === st.name && subTypes.indexOf(n.type) !== -1;
      });
    });
    let maxSubRows = 1;
    laneSubs.forEach(function (l) { if (l.length > maxSubRows) maxSubRows = l.length; });

    const width = Math.max(container.clientWidth || 800, stations.length * LANE_W + 160);
    const height = subY + maxSubRows * (SUBROW_H + 8) + (alarmCodes.length ? 90 : 20);

    container.innerHTML = "";
    const svg = svgEl("svg", {
      width: width, height: height, viewBox: "0 0 " + width + " " + height,
      class: "kg-svg",
    });

    const crumb = [enterprise, site, area, line].filter(Boolean)
      .map(function (n) { return n.name; }).join(" ▸ ");
    svg.appendChild(svgEl("text", { x: 10, y: breadcrumbY, class: "kg-crumb" }, crumb));

    svg.appendChild(svgEl("text", { x: 10, y: flowY + STATION_H / 2, class: "kg-endpoint" }, "Source ∞"));

    stations.forEach(function (st, i) {
      const x = laneX(i);
      const midY = flowY + STATION_H / 2;

      if (i < buffers.length) {
        const bx = x + STATION_W + 4;
        svg.appendChild(svgEl("line", {
          x1: x + STATION_W, y1: midY, x2: bx, y2: midY, class: "kg-edge kg-edge-flow",
        }));
        svg.appendChild(svgEl("line", {
          x1: bx + BUF_W, y1: midY, x2: laneX(i + 1), y2: midY, class: "kg-edge kg-edge-flow",
        }));
      }

      const g = svgEl("g", {
        class: "kg-node kg-node-station", "data-id": st.id,
        transform: "translate(" + x + "," + flowY + ")",
      });
      g.appendChild(svgEl("rect", { width: STATION_W, height: STATION_H, class: "kg-rect kg-rect-station" }));
      g.appendChild(svgEl("text", { x: 8, y: 18, class: "kg-label kg-label-strong" }, st.name));
      g.appendChild(svgEl("text", { x: 8, y: 34, class: "kg-label kg-label-dim" }, stationLine2(st)));
      const hl = healthLabel(st);
      if (hl) g.appendChild(svgEl("text", { x: 8, y: 48, class: "kg-label kg-label-dim" }, hl));
      g.addEventListener("click", function () { onNodeClick(st); });
      svg.appendChild(g);

      if (i < buffers.length) {
        const b = buffers[i];
        const bx = x + STATION_W + 4;
        const bg = svgEl("g", {
          class: "kg-node kg-node-buffer", "data-id": b.id,
          transform: "translate(" + bx + "," + (flowY + 10) + ")",
        });
        bg.appendChild(svgEl("rect", { width: BUF_W, height: STATION_H - 20, class: "kg-rect kg-rect-buffer" }));
        bg.appendChild(svgEl("text", { x: 4, y: 14, class: "kg-label kg-label-type" }, "buffer"));
        bg.appendChild(svgEl("text", { x: 4, y: 30, class: "kg-label" }, b.name + " · " + b.capacity));
        bg.addEventListener("click", function () { onNodeClick(b); });
        svg.appendChild(bg);
      }
    });
    svg.appendChild(svgEl("text", {
      x: laneX(stations.length) + 4, y: flowY + STATION_H / 2, class: "kg-endpoint",
    }, "Sink ∞"));

    const alarmPos = {};
    stations.forEach(function (st, i) {
      const x = laneX(i);
      laneSubs[i].forEach(function (sub, r) {
        const sy = subY + r * (SUBROW_H + 8);
        svg.appendChild(svgEl("line", {
          x1: x + 10, y1: sy + SUBROW_H / 2, x2: x + 10, y2: flowY + STATION_H,
          class: "kg-edge kg-edge-" + sub.type.toLowerCase(),
        }));
        const g = svgEl("g", {
          class: "kg-node kg-node-sub kg-node-" + sub.type.toLowerCase(), "data-id": sub.id,
          transform: "translate(" + x + "," + sy + ")",
        });
        g.appendChild(svgEl("rect", {
          width: SUB_W, height: SUBROW_H, class: "kg-rect kg-rect-sub kg-rect-" + sub.type.toLowerCase(),
        }));
        const lbl = subEntityLabel(sub);
        g.appendChild(svgEl("text", { x: 6, y: 14, class: "kg-label kg-label-type" }, lbl.type));
        g.appendChild(svgEl("text", { x: 6, y: 30, class: "kg-label" }, lbl.main));
        g.addEventListener("click", function () { onNodeClick(sub); });
        svg.appendChild(g);
      });
    });

    if (alarmCodes.length) {
      const bandY = height - 70;
      alarmCodes.forEach(function (code, i) {
        const ax = 60 + i * 130;
        alarmPos[code.id] = { x: ax + 55, y: bandY };
        const g = svgEl("g", {
          class: "kg-node kg-node-alarm", "data-id": code.id,
          transform: "translate(" + ax + "," + bandY + ")",
        });
        g.appendChild(svgEl("rect", { width: 110, height: 40, class: "kg-rect kg-rect-alarm" }));
        g.appendChild(svgEl("text", { x: 6, y: 15, class: "kg-label kg-label-type" }, code.severity));
        g.appendChild(svgEl("text", { x: 6, y: 31, class: "kg-label" }, code.name));
        g.addEventListener("click", function () { onNodeClick(code); });
        svg.appendChild(g);
      });

      edges.filter(function (e) { return e.type === "CAN_RAISE"; }).forEach(function (e) {
        const st = byId[e.source];
        const target = alarmPos[e.target];
        if (!st || !target || st.type !== "Station") return;
        const idx = stations.indexOf(st);
        if (idx < 0) return;
        const sx = laneX(idx) + STATION_W / 2;
        const sy2 = flowY + STATION_H;
        const codeNode = byId[e.target];
        const path = svgEl("path", {
          d: "M" + sx + "," + sy2 + " C" + sx + "," + (target.y - 20) +
             " " + target.x + "," + (sy2 + 20) + " " + target.x + "," + target.y,
          class: "kg-edge " + alarmEdgeClass(codeNode.name),
        });
        svg.insertBefore(path, svg.firstChild);
      });
    }

    container.appendChild(svg);
  }

  window.renderKGGraph = renderKGGraph;
})();

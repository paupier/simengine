// entity-forms.js — the flow-line editor (station cards, buffers, health) and
// its repeatable-list sub-entity forms (process values, failure modes, cycle
// stops). Every render function mutates the passed station object directly
// and calls `rerender()` after structural changes (add/remove/profile
// switch), matching the Edit-mode rendering pattern in the plan's Global
// Constraints.
//
// This file is loaded via a plain <script src> (not a Jinja template), after
// base.html's inline <script> block has already run. `esc()` is declared there
// as a top-level `function esc(s) {...}` in a classic (non-module) script, so
// it is a property of `window` and reachable here as a bare global — same
// escaping convention used throughout configure.html's own script block.
(function () {
  const PV_PROFILE_FIELDS = {
    cycle_peak: ["baseline"],
    first_order_lag: ["setpoint", "tau", "initial", "ambient"],
    cycle_ramp: [],  // uses `range`, handled specially (2 inputs)
    constant_noise: ["mean"],
  };
  const PV_PROFILES = Object.keys(PV_PROFILE_FIELDS);

  function numField(label, obj, key, initial) {
    const wrap = document.createElement("label");
    wrap.className = "fe-field";
    wrap.innerHTML = `${esc(label)} <input type="number" step="any" value="${
      esc(obj[key] != null ? obj[key] : initial)}">`;
    wrap.querySelector("input").oninput = (e) => {
      obj[key] = e.target.value === "" ? initial : parseFloat(e.target.value);
      scheduleValidate();
    };
    return wrap;
  }

  function textField(label, obj, key, initial) {
    const wrap = document.createElement("label");
    wrap.className = "fe-field";
    wrap.innerHTML = `${esc(label)} <input type="text" value="${esc(obj[key] != null ? obj[key] : initial)}">`;
    wrap.querySelector("input").oninput = (e) => { obj[key] = e.target.value; scheduleValidate(); };
    return wrap;
  }

  function optionalDistField(label, obj, key, row) {
    const wrap = document.createElement("div");
    wrap.className = "fe-field";
    const cb = document.createElement("label");
    cb.style.cssText = "font-size:11px;display:flex;gap:6px;align-items:center";
    cb.innerHTML = `<input type="checkbox" ${obj[key] ? "checked" : ""}> ${esc(label)}`;
    const pickerDiv = document.createElement("div");
    wrap.appendChild(cb);
    wrap.appendChild(pickerDiv);
    function draw() {
      pickerDiv.innerHTML = "";
      if (obj[key]) {
        createDistributionPicker(pickerDiv, obj[key], (cfg) => { obj[key] = cfg; scheduleValidate(); });
      }
    }
    cb.querySelector("input").onchange = (e) => {
      if (e.target.checked) obj[key] = { distribution: "normal", mean: 0, std: 1 };
      else delete obj[key];
      draw();
      scheduleValidate();
    };
    draw();
    return wrap;
  }

  function blankPV(name) {
    return {
      name: name, unit: "unit", profile: "constant_noise", mean: 0,
    };
  }

  function renderPVForm(container, pv, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("name", pv, "name", "PV" + index));
    container.appendChild(textField("unit", pv, "unit", "unit"));

    const profileField = document.createElement("label");
    profileField.className = "fe-field";
    profileField.innerHTML = `profile <select>${PV_PROFILES.map(p =>
      `<option value="${esc(p)}" ${p === pv.profile ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>`;
    profileField.querySelector("select").onchange = (e) => {
      const newProfile = e.target.value;
      // strip old profile-specific keys, keep name/unit/noise/health_drift/alarm_*
      ["baseline", "peak", "setpoint", "tau", "initial", "ambient", "range", "mean"]
        .forEach(k => delete pv[k]);
      pv.profile = newProfile;
      if (newProfile === "cycle_peak") { pv.baseline = 0; pv.peak = { distribution: "normal", mean: 10, std: 1 }; }
      else if (newProfile === "first_order_lag") { pv.setpoint = 0; pv.tau = 60; pv.initial = 0; }
      else if (newProfile === "cycle_ramp") { pv.range = [0, 1]; }
      else if (newProfile === "constant_noise") { pv.mean = 0; }
      rerender();
    };
    container.appendChild(profileField);

    if (pv.profile === "cycle_peak") {
      container.appendChild(numField("baseline", pv, "baseline", 0));
      const peakField = document.createElement("div");
      peakField.className = "fe-field";
      peakField.innerHTML = "<span>peak</span>";
      const peakPicker = document.createElement("div");
      peakField.appendChild(peakPicker);
      createDistributionPicker(peakPicker, pv.peak, (cfg) => { pv.peak = cfg; scheduleValidate(); });
      container.appendChild(peakField);
    } else if (pv.profile === "first_order_lag") {
      ["setpoint", "tau", "initial", "ambient"].forEach(f =>
        container.appendChild(numField(f, pv, f, f === "tau" ? 60 : 0)));
    } else if (pv.profile === "cycle_ramp") {
      const rangeField = document.createElement("label");
      rangeField.className = "fe-field";
      const r = pv.range || [0, 1];
      rangeField.innerHTML = `range
        <input type="number" step="any" class="r-lo" value="${esc(r[0])}" style="width:70px">
        <input type="number" step="any" class="r-hi" value="${esc(r[1])}" style="width:70px">`;
      rangeField.querySelector(".r-lo").oninput = (e) => { pv.range = [parseFloat(e.target.value) || 0, (pv.range || r)[1]]; scheduleValidate(); };
      rangeField.querySelector(".r-hi").oninput = (e) => { pv.range = [(pv.range || r)[0], parseFloat(e.target.value) || 0]; scheduleValidate(); };
      container.appendChild(rangeField);
    } else if (pv.profile === "constant_noise") {
      container.appendChild(numField("mean", pv, "mean", 0));
    }

    container.appendChild(numField("health_drift", pv, "health_drift", 0));
    container.appendChild(optionalDistField("noise", pv, "noise"));
    container.appendChild(numField("alarm_high", pv, "alarm_high", null));
    container.appendChild(numField("alarm_low", pv, "alarm_low", null));

  }

  function pvSummaryCells(pv) {
    const keyVal = pv.profile === "cycle_peak" ? "baseline " + (pv.baseline != null ? pv.baseline : 0)
      : pv.profile === "first_order_lag" ? "setpoint " + (pv.setpoint != null ? pv.setpoint : 0)
      : pv.profile === "cycle_ramp" ? "range " + JSON.stringify(pv.range || [0, 1])
      : "mean " + (pv.mean != null ? pv.mean : 0);
    const alarms = [pv.alarm_high != null ? "≤" + pv.alarm_high : null,
      pv.alarm_low != null ? "≥" + pv.alarm_low : null].filter(Boolean).join(" ") || "—";
    return [pv.name, pv.unit, pv.profile, keyVal, alarms];
  }

  function renderProcessValues(container, station, rerender) {
    container.innerHTML = "";
    const list = station.process_values || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Process Values</h4>";

    const table = document.createElement("table");
    table.className = "ed-table";
    table.innerHTML = "<thead><tr><th>name</th><th>unit</th><th>profile</th><th>key value</th><th>alarms</th><th></th></tr></thead>";
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);

    list.forEach((pv, i) => {
      const summaryRow = document.createElement("tr");
      summaryRow.className = "ed-table-row";
      summaryRow.innerHTML = pvSummaryCells(pv).map(c => `<td>${esc(c)}</td>`).join("") + "<td></td>";
      const removeBtn = document.createElement("button");
      removeBtn.className = "quiet fe-remove-btn";
      removeBtn.textContent = "×";
      removeBtn.onclick = (e) => {
        e.stopPropagation();
        station.process_values.splice(i, 1);
        rerender();
      };
      summaryRow.lastElementChild.appendChild(removeBtn);

      const expandRow = document.createElement("tr");
      expandRow.className = "ed-table-expand";
      expandRow.hidden = true;
      const expandCell = document.createElement("td");
      expandCell.colSpan = 6;
      expandRow.appendChild(expandCell);

      summaryRow.onclick = () => {
        const wasHidden = expandRow.hidden;
        tbody.querySelectorAll(".ed-table-expand").forEach(r => { r.hidden = true; });
        if (wasHidden) {
          renderPVForm(expandCell, pv, station, i, rerender);
          expandRow.hidden = false;
        }
      };

      tbody.appendChild(summaryRow);
      tbody.appendChild(expandRow);
    });

    section.appendChild(table);

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add process value";
    addBtn.onclick = () => {
      if (!station.process_values) station.process_values = [];
      station.process_values.push(blankPV("PV" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }

  function blankFailureMode(name) {
    return {
      name: name, type: "random",
      mttf: { distribution: "exponential", mean: 10000 },
      mttr: { distribution: "lognormal", mean: 300, std: 60 },
    };
  }

  function renderFailureModeForm(container, fm, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("name", fm, "name", "failure_mode_" + index));
    container.appendChild(textField("type", fm, "type", "random"));

    const mttfField = document.createElement("div");
    mttfField.className = "fe-field";
    mttfField.innerHTML = "<span>mttf</span>";
    const mttfPicker = document.createElement("div");
    mttfField.appendChild(mttfPicker);
    createDistributionPicker(mttfPicker, fm.mttf, (cfg) => { fm.mttf = cfg; scheduleValidate(); });
    container.appendChild(mttfField);

    const mttrField = document.createElement("div");
    mttrField.className = "fe-field";
    mttrField.innerHTML = "<span>mttr</span>";
    const mttrPicker = document.createElement("div");
    mttrField.appendChild(mttrPicker);
    createDistributionPicker(mttrPicker, fm.mttr, (cfg) => { fm.mttr = cfg; scheduleValidate(); });
    container.appendChild(mttrField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.failure_modes.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }

  function renderFailureModes(container, station, rerender) {
    container.innerHTML = "";
    const list = station.failure_modes || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Failure Modes</h4>";

    list.forEach((fm, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderFailureModeForm(row, fm, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add failure mode";
    addBtn.onclick = () => {
      if (!station.failure_modes) station.failure_modes = [];
      station.failure_modes.push(blankFailureMode("failure_mode_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }

  function blankCycleStop(reason) {
    return {
      reason: reason,
      mtbe: { distribution: "exponential", mean: 900 },
      duration: { distribution: "lognormal", mean: 25, std: 10 },
    };
  }

  function renderCycleStopForm(container, cs, station, index, rerender) {
    container.innerHTML = "";
    container.appendChild(textField("reason", cs, "reason", "CS_" + index));

    const mtbeField = document.createElement("div");
    mtbeField.className = "fe-field";
    mtbeField.innerHTML = "<span>mtbe</span>";
    const mtbePicker = document.createElement("div");
    mtbeField.appendChild(mtbePicker);
    createDistributionPicker(mtbePicker, cs.mtbe, (cfg) => { cs.mtbe = cfg; scheduleValidate(); });
    container.appendChild(mtbeField);

    const durField = document.createElement("div");
    durField.className = "fe-field";
    durField.innerHTML = "<span>duration</span>";
    const durPicker = document.createElement("div");
    durField.appendChild(durPicker);
    createDistributionPicker(durPicker, cs.duration, (cfg) => { cs.duration = cfg; scheduleValidate(); });
    container.appendChild(durField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => { station.cycle_stops.splice(index, 1); rerender(); };
    container.appendChild(removeBtn);
  }

  function renderCycleStops(container, station, rerender) {
    container.innerHTML = "";
    const list = station.cycle_stops || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Cycle Stops</h4>";

    list.forEach((cs, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderCycleStopForm(row, cs, station, i, rerender);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-btn";
    addBtn.textContent = "+ Add cycle stop";
    addBtn.onclick = () => {
      if (!station.cycle_stops) station.cycle_stops = [];
      station.cycle_stops.push(blankCycleStop("CS_" + (list.length + 1)));
      rerender();
    };
    section.appendChild(addBtn);

    container.appendChild(section);
  }

  // ---- Pipeline row (View mode's renderer, reused) + single-selection detail panel ----
  function blankStation(name) {
    return { name: name, cycle_time: 10.0 };
  }
  function blankBuffer(name) {
    return { name: name, capacity: 10 };
  }
  function nextName(prefix, existing) {
    let i = 1;
    while (existing.includes(prefix + i)) i++;
    return prefix + i;
  }

  let selectedNode = null;  // { kind: "station"|"buffer", data: <EDIT_DRAFT.stations[i] or .buffers[i]> } | null
  let pipelineRequestId = 0;

  async function renderPipelineRow(container, draft) {
    const myId = ++pipelineRequestId;
    let nodeLink;
    try {
      nodeLink = await jsend("/api/v1/kg/preview", "POST",
        { config: draft, name: currentEditScenario || "draft" });
    } catch (e) {
      return;  // network hiccup or transiently-invalid draft — keep showing the last good row
    }
    if (myId !== pipelineRequestId) return;  // stale response, discard (same race-guard runValidate() uses)
    renderKGGraph(container, nodeLink, { flowOnly: true, onNodeClick: onPipelineNodeClick });
  }

  function onPipelineNodeClick(node) {
    if (node.type === "Station") {
      const st = EDIT_DRAFT.stations.find(function (s) { return s.name === node.name; });
      selectedNode = st ? { kind: "station", data: st } : null;
    } else if (node.type === "Buffer") {
      const b = EDIT_DRAFT.buffers.find(function (b) { return b.name === node.name; });
      selectedNode = b ? { kind: "buffer", data: b } : null;
    } else {
      return;
    }
    renderDetailPanel($("edit-detail"));
  }

  function selectStation(st) {
    selectedNode = { kind: "station", data: st };
  }
  function clearSelection() {
    selectedNode = null;
  }
  function addStation(draft) {
    const names = draft.stations.map(function (s) { return s.name; });
    const newStation = blankStation(nextName("S", names));
    if (draft.stations.length > 0) {
      draft.buffers.push(blankBuffer(nextName("B", draft.buffers.map(function (b) { return b.name; }))));
    }
    draft.stations.push(newStation);
    selectedNode = { kind: "station", data: newStation };
  }

  function renderDetailPanel(container) {
    if (!selectedNode) {
      container.innerHTML = '<span class="kg-detail-empty">Click a station or buffer to edit it.</span>';
      return;
    }
    if (selectedNode.kind === "station") {
      if (EDIT_DRAFT.stations.indexOf(selectedNode.data) === -1) { selectedNode = null; return renderDetailPanel(container); }
      renderStationDetail(container, selectedNode.data);
    } else if (selectedNode.kind === "buffer") {
      if (EDIT_DRAFT.buffers.indexOf(selectedNode.data) === -1) { selectedNode = null; return renderDetailPanel(container); }
      renderBufferDetail(container, selectedNode.data);
    }
  }

  function renderStationDetail(el, st) {
    el.innerHTML = "";
    const h = document.createElement("h3");
    h.textContent = st.name;
    el.appendChild(h);

    const fields = document.createElement("div");
    fields.className = "ed-fields";
    el.appendChild(fields);

    const nameField = document.createElement("label");
    nameField.innerHTML = `name <input type="text" class="fe-st-name" value="${esc(st.name)}">`;
    nameField.querySelector("input").oninput = (e) => { st.name = e.target.value; scheduleValidate(); };
    fields.appendChild(nameField);

    const cycleField = document.createElement("label");
    const isPpm = st.target_ppm != null;
    cycleField.innerHTML = `rate
      <select class="fe-cycle-mode">
        <option value="cycle_time" ${!isPpm ? "selected" : ""}>cycle_time (s)</option>
        <option value="target_ppm" ${isPpm ? "selected" : ""}>target_ppm</option>
      </select>
      <input type="number" step="any" class="fe-cycle-val"
        value="${esc(isPpm ? st.target_ppm : (st.cycle_time != null ? st.cycle_time : 10))}">`;
    const modeSel = cycleField.querySelector(".fe-cycle-mode");
    const valInput = cycleField.querySelector(".fe-cycle-val");
    function applyCycleMode() {
      const parsed = parseFloat(valInput.value);
      const value = Number.isNaN(parsed) ? 1 : parsed;
      if (modeSel.value === "target_ppm") { st.target_ppm = value; delete st.cycle_time; }
      else { st.cycle_time = value; delete st.target_ppm; }
      scheduleValidate();
    }
    modeSel.onchange = () => { applyCycleMode(); renderEditMode(); };
    valInput.oninput = applyCycleMode;
    fields.appendChild(cycleField);

    const defectField = document.createElement("label");
    defectField.innerHTML = `defect_rate <input type="number" step="any" class="fe-defect"
      value="${esc(st.defect_rate != null ? st.defect_rate : 0)}">`;
    defectField.querySelector("input").oninput = (e) => { st.defect_rate = parseFloat(e.target.value) || 0; scheduleValidate(); };
    fields.appendChild(defectField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = EDIT_DRAFT.stations, buffers = EDIT_DRAFT.buffers;
      const i = stations.indexOf(st);
      if (i < 0) return;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      selectedNode = null;
      renderEditMode();
    };
    el.appendChild(removeBtn);

    // ---- Health sub-section ----
    const healthSection = document.createElement("div");
    healthSection.className = "fe-sub-section";
    const healthEnabled = !!st.health;
    healthSection.innerHTML = `<h4>Health</h4>
      <label style="font-size:11px;display:flex;gap:6px;align-items:center">
        <input type="checkbox" class="fe-health-enabled" ${healthEnabled ? "checked" : ""}> enabled
      </label>
      <div class="fe-health-fields ed-fields"></div>`;
    const fieldsDiv = healthSection.querySelector(".fe-health-fields");
    function renderHealthFields() {
      fieldsDiv.innerHTML = "";
      if (!st.health) return;
      const h = st.health;
      const hMaxField = document.createElement("label");
      hMaxField.innerHTML = `h_max <input type="number" class="fe-h-hmax" value="${esc(h.h_max != null ? h.h_max : 1)}">`;
      hMaxField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.h_max = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(hMaxField);

      const pDegField = document.createElement("label");
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${esc(h.p_degrade != null ? h.p_degrade : 0.001)}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; scheduleValidate(); };
      fieldsDiv.appendChild(pDegField);

      const cbmField = document.createElement("label");
      cbmField.innerHTML = `cbm_threshold <input type="number" class="fe-h-cbm"
        value="${esc(h.cbm_threshold != null ? h.cbm_threshold : (h.h_max || 1))}">`;
      cbmField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.cbm_threshold = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(cbmField);

      const mttrField = document.createElement("div");
      mttrField.innerHTML = `<span>mttr</span>`;
      const mttrPicker = document.createElement("div");
      mttrField.appendChild(mttrPicker);
      createDistributionPicker(mttrPicker, h.mttr, (cfg) => { h.mttr = cfg; scheduleValidate(); });
      fieldsDiv.appendChild(mttrField);
    }
    renderHealthFields();

    healthSection.querySelector(".fe-health-enabled").onchange = (e) => {
      if (e.target.checked) {
        st.health = { h_max: 3, p_degrade: 0.001, cbm_threshold: 3,
          mttr: { distribution: "lognormal", mean: 120, std: 30 } };
      } else {
        delete st.health;
      }
      renderEditMode();
    };
    el.appendChild(healthSection);

    const pvContainer = document.createElement("div");
    el.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);
  }

  function renderBufferDetail(el, b) {
    el.innerHTML = "";
    const h = document.createElement("h3");
    h.textContent = b.name;
    el.appendChild(h);

    const fields = document.createElement("div");
    fields.className = "ed-fields";
    el.appendChild(fields);

    const nameField = document.createElement("label");
    nameField.innerHTML = `name <input type="text" class="fe-buf-name" value="${esc(b.name)}">`;
    nameField.querySelector("input").oninput = (e) => { b.name = e.target.value; scheduleValidate(); };
    fields.appendChild(nameField);

    const capField = document.createElement("label");
    capField.innerHTML = `capacity <input type="number" class="fe-buf-cap" value="${esc(b.capacity)}">`;
    capField.querySelector("input").oninput = (e) => {
      const parsed = parseInt(e.target.value, 10);
      b.capacity = Number.isNaN(parsed) ? 1 : parsed;
      scheduleValidate();
    };
    fields.appendChild(capField);
  }

  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
  window.entityForms.renderPipelineRow = renderPipelineRow;
  window.entityForms.renderDetailPanel = renderDetailPanel;
  window.entityForms.selectStation = selectStation;
  window.entityForms.clearSelection = clearSelection;
  window.entityForms.addStation = addStation;
  window.entityForms.blankStation = blankStation;
  window.entityForms.blankBuffer = blankBuffer;
})();

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

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove";
    removeBtn.onclick = () => {
      station.process_values.splice(index, 1);
      rerender();
    };
    container.appendChild(removeBtn);
  }

  function renderProcessValues(container, station, rerender) {
    container.innerHTML = "";
    const list = station.process_values || [];
    const section = document.createElement("div");
    section.className = "fe-sub-section";
    section.innerHTML = "<h4>Process Values</h4>";

    list.forEach((pv, i) => {
      const row = document.createElement("div");
      row.className = "fe-sub-row";
      section.appendChild(row);
      renderPVForm(row, pv, station, i, rerender);
    });

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

  function buildStationBody(body, st, i, draft) {
    body.innerHTML = "";

    const nameField = document.createElement("label");
    nameField.className = "fe-field";
    nameField.innerHTML = `name <input type="text" class="fe-st-name" value="${esc(st.name)}">`;
    nameField.querySelector("input").oninput = (e) => { st.name = e.target.value; scheduleValidate(); };
    body.appendChild(nameField);

    const cycleField = document.createElement("label");
    cycleField.className = "fe-field";
    const isPpm = st.target_ppm != null;
    cycleField.innerHTML = `
      <span>rate</span>
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
      if (modeSel.value === "target_ppm") {
        st.target_ppm = value;
        delete st.cycle_time;
      } else {
        st.cycle_time = value;
        delete st.target_ppm;
      }
      scheduleValidate();
    }
    modeSel.onchange = () => { applyCycleMode(); renderEditMode(); };
    valInput.oninput = applyCycleMode;
    body.appendChild(cycleField);

    const defectField = document.createElement("label");
    defectField.className = "fe-field";
    defectField.innerHTML = `defect_rate <input type="number" step="any" class="fe-defect"
      value="${esc(st.defect_rate != null ? st.defect_rate : 0)}">`;
    defectField.querySelector("input").oninput = (e) => { st.defect_rate = parseFloat(e.target.value) || 0; scheduleValidate(); };
    body.appendChild(defectField);

    const removeBtn = document.createElement("button");
    removeBtn.className = "quiet fe-remove-btn";
    removeBtn.textContent = "Remove station";
    removeBtn.onclick = () => {
      const stations = draft.stations, buffers = draft.buffers;
      const bufIdx = i > 0 ? i - 1 : 0;
      if (buffers.length > 0) buffers.splice(bufIdx, 1);
      stations.splice(i, 1);
      expandedStations.delete(st);
      renderEditMode();
    };
    body.appendChild(removeBtn);

    // ---- Health sub-section ----
    const healthSection = document.createElement("div");
    healthSection.className = "fe-sub-section";
    const healthEnabled = !!st.health;
    healthSection.innerHTML = `<h4>Health</h4>
      <label style="font-size:11px;display:flex;gap:6px;align-items:center">
        <input type="checkbox" class="fe-health-enabled" ${healthEnabled ? "checked" : ""}> enabled
      </label>
      <div class="fe-health-fields"></div>`;
    const fieldsDiv = healthSection.querySelector(".fe-health-fields");
    function renderHealthFields() {
      fieldsDiv.innerHTML = "";
      if (!st.health) return;
      const h = st.health;
      const hMaxField = document.createElement("label");
      hMaxField.className = "fe-field";
      hMaxField.innerHTML = `h_max <input type="number" class="fe-h-hmax" value="${esc(h.h_max != null ? h.h_max : 1)}">`;
      hMaxField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.h_max = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(hMaxField);

      const pDegField = document.createElement("label");
      pDegField.className = "fe-field";
      pDegField.innerHTML = `p_degrade <input type="number" step="any" class="fe-h-pdeg"
        value="${esc(h.p_degrade != null ? h.p_degrade : 0.001)}">`;
      pDegField.querySelector("input").oninput = (e) => { h.p_degrade = parseFloat(e.target.value) || 0; scheduleValidate(); };
      fieldsDiv.appendChild(pDegField);

      const cbmField = document.createElement("label");
      cbmField.className = "fe-field";
      cbmField.innerHTML = `cbm_threshold <input type="number" class="fe-h-cbm"
        value="${esc(h.cbm_threshold != null ? h.cbm_threshold : (h.h_max || 1))}">`;
      cbmField.querySelector("input").oninput = (e) => {
        const parsed = parseInt(e.target.value, 10);
        h.cbm_threshold = Number.isNaN(parsed) ? 1 : parsed;
        scheduleValidate();
      };
      fieldsDiv.appendChild(cbmField);

      const mttrField = document.createElement("div");
      mttrField.className = "fe-field";
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
    body.appendChild(healthSection);

    const pvContainer = document.createElement("div");
    body.appendChild(pvContainer);
    renderProcessValues(pvContainer, st, renderEditMode);

    const fmContainer = document.createElement("div");
    body.appendChild(fmContainer);
    renderFailureModes(fmContainer, st, renderEditMode);

    const csContainer = document.createElement("div");
    body.appendChild(csContainer);
    renderCycleStops(csContainer, st, renderEditMode);
  }

  // ---- Flow-line editor: stations, buffers, health ----
  // Keyed by station object identity (not array index) so removing a station
  // doesn't shift the expand/collapse state of stations after it — station
  // objects persist through array splices, only their position changes.
  const expandedStations = new Set();

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

  function stationSummary(st) {
    const pv = (st.process_values || []).length;
    const fm = (st.failure_modes || []).length;
    const cs = (st.cycle_stops || []).length;
    return `${pv} PV · ${fm} FM · ${cs} CS`;
  }

  function renderFlowEditor(container, draft) {
    const stations = draft.stations;
    const buffers = draft.buffers;
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "flow-editor";

    stations.forEach((st, i) => {
      const card = document.createElement("div");
      card.className = "fe-station";
      card.dataset.stationIndex = i;
      const expanded = expandedStations.has(st);

      const head = document.createElement("div");
      head.className = "fe-head";
      head.innerHTML = `<div><div class="fe-name">${esc(st.name)}</div>
        <div class="fe-summary">${st.cycle_time != null ? esc(st.cycle_time) + "s" : (esc(st.target_ppm) + " ppm")}
          · ${esc(stationSummary(st))}</div></div>`;
      head.onclick = () => {
        if (expanded) expandedStations.delete(st); else expandedStations.add(st);
        renderEditMode();
      };
      card.appendChild(head);

      const body = document.createElement("div");
      body.className = "fe-body" + (expanded ? "" : " collapsed");
      if (expanded) buildStationBody(body, st, i, draft);
      card.appendChild(body);

      wrap.appendChild(card);

      if (i < buffers.length) {
        const b = buffers[i];
        const bw = document.createElement("div");
        bw.className = "fe-buffer";
        bw.innerHTML = `<label class="fe-field" style="font-size:10px">name
          <input type="text" value="${esc(b.name)}" class="fe-buf-name"></label>
          <input type="number" value="${esc(b.capacity)}" class="fe-buf-cap">`;
        bw.querySelector(".fe-buf-name").oninput = (e) => { b.name = e.target.value; scheduleValidate(); };
        bw.querySelector(".fe-buf-cap").oninput = (e) => {
          const parsed = parseInt(e.target.value, 10);
          b.capacity = Number.isNaN(parsed) ? 1 : parsed;
          scheduleValidate();
        };
        wrap.appendChild(bw);
      }
    });

    const addBtn = document.createElement("button");
    addBtn.className = "quiet fe-add-station";
    addBtn.textContent = "+ Add Station";
    addBtn.onclick = () => {
      const names = stations.map(s => s.name);
      const newStation = blankStation(nextName("S", names));
      if (stations.length > 0) {
        buffers.push(blankBuffer(nextName("B", buffers.map(b => b.name))));
      }
      stations.push(newStation);
      expandedStations.add(newStation);
      renderEditMode();
    };
    wrap.appendChild(addBtn);

    container.appendChild(wrap);
  }

  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
  window.entityForms.renderFlowEditor = renderFlowEditor;
  window.entityForms.blankStation = blankStation;
  window.entityForms.blankBuffer = blankBuffer;
  window.entityForms.expandedStations = expandedStations;
})();

// entity-forms.js — repeatable-list forms for station sub-entities:
// process values (this task), failure modes and cycle stops (added next task).
// Every render function mutates the passed station object directly and calls
// `rerender()` after structural changes (add/remove/profile switch), matching
// the Edit-mode rendering pattern in the plan's Global Constraints.
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

  window.entityForms = window.entityForms || {};
  window.entityForms.renderProcessValues = renderProcessValues;
  window.entityForms.renderFailureModes = renderFailureModes;
  window.entityForms.renderCycleStops = renderCycleStops;
})();

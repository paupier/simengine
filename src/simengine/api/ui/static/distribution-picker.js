// distribution-picker.js — reusable widget for DistributionFactory configs.
// Verified against src/simengine/config/distributions.py: DistributionFactory.create.
(function () {
  const DIST_FIELDS = {
    constant: ["value"],
    exponential: ["mean"],
    weibull: ["shape", "scale"],
    lognormal: ["mean", "std"],
    normal: ["mean", "std"],
    uniform: ["min", "max"],
  };
  const DIST_TYPES = Object.keys(DIST_FIELDS);

  function createDistributionPicker(container, value, onChange) {
    const cfg = Object.assign({ distribution: "constant", value: 0 }, value || {});

    function render() {
      container.innerHTML = "";
      container.classList.add("dist-picker");

      const select = document.createElement("select");
      select.className = "dist-type";
      DIST_TYPES.forEach(function (t) {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        if (t === cfg.distribution) opt.selected = true;
        select.appendChild(opt);
      });
      select.onchange = function () {
        const newType = select.value;
        const next = { distribution: newType };
        DIST_FIELDS[newType].forEach(function (f) {
          next[f] = cfg[f] != null ? cfg[f] : 0;
        });
        Object.keys(cfg).forEach(function (k) { delete cfg[k]; });
        Object.assign(cfg, next);
        render();
        onChange(cfg);
      };
      container.appendChild(select);

      DIST_FIELDS[cfg.distribution].forEach(function (field) {
        const label = document.createElement("label");
        label.className = "dist-field";
        label.appendChild(document.createTextNode(field + " "));
        const input = document.createElement("input");
        input.type = "number";
        input.step = "any";
        input.value = cfg[field] != null ? cfg[field] : "";
        input.oninput = function () {
          cfg[field] = input.value === "" ? 0 : parseFloat(input.value);
          onChange(cfg);
        };
        label.appendChild(input);
        container.appendChild(label);
      });
    }

    render();
    return cfg;
  }

  window.createDistributionPicker = createDistributionPicker;
  window.DIST_FIELDS = DIST_FIELDS;
})();

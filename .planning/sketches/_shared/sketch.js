// Sketch chrome shared by every dashboard sketch: variant tabs, toolbar, toast.
// Variants are `.variant` elements with data-label; data-winner marks the pick.
(function () {
  const root = document.getElementById("sketch-root");
  const variants = [...document.querySelectorAll(".variant")];

  // --- variant tabs -------------------------------------------------------
  const nav = document.createElement("div");
  nav.id = "variant-nav";
  nav.innerHTML = `<span class="sketch-title">${document.title}</span>`;
  variants.forEach((v) => {
    const b = document.createElement("button");
    b.className = "variant-tab";
    b.textContent = v.dataset.label + (v.hasAttribute("data-winner") ? " ★ Selected" : "");
    b.onclick = () => show(v.id);
    b.dataset.for = v.id;
    nav.appendChild(b);
  });
  document.body.prepend(nav);

  function show(id) {
    variants.forEach((v) => v.classList.toggle("active", v.id === id));
    nav.querySelectorAll(".variant-tab").forEach((t) => t.classList.toggle("active", t.dataset.for === id));
    history.replaceState(null, "", "#" + id);
    window.dispatchEvent(new CustomEvent("variant", { detail: id }));
  }
  const start = variants.find((v) => "#" + v.id === location.hash) || variants.find((v) => v.hasAttribute("data-winner")) || variants[0];
  show(start.id);

  // --- toolbar ------------------------------------------------------------
  const tools = document.createElement("div");
  tools.id = "sketch-tools";
  tools.style.cssText =
    "position:fixed;bottom:12px;right:12px;z-index:9999;font:12px system-ui;background:rgba(0,0,0,.78);color:#fff;" +
    "padding:8px 10px;border-radius:8px;opacity:.4;transition:opacity .2s;display:flex;gap:8px;align-items:center";
  tools.onmouseenter = () => (tools.style.opacity = "1");
  tools.onmouseleave = () => (tools.style.opacity = ".4");
  const btn = "background:rgba(255,255,255,.12);border:0;color:#fff;border-radius:5px;padding:3px 7px;cursor:pointer";
  tools.innerHTML = `
    <select id="st-theme" style="${btn}">
      <option value="">Auto</option><option value="light">Light</option><option value="dark">Dark</option>
    </select>
    <button data-w="375" style="${btn}">Phone</button>
    <button data-w="768" style="${btn}">Tablet</button>
    <button data-w="1280" style="${btn}">Desktop</button>
    <button data-w="" style="${btn}">Full</button>
    <label style="display:flex;gap:4px;align-items:center;cursor:pointer"><input type="checkbox" id="st-annot">Annotate</label>`;
  document.body.appendChild(tools);
  tools.querySelector("#st-theme").onchange = (e) =>
    e.target.value ? document.documentElement.setAttribute("data-theme", e.target.value) : document.documentElement.removeAttribute("data-theme");
  tools.querySelectorAll("[data-w]").forEach((b) => (b.onclick = () => (root.style.maxWidth = b.dataset.w ? b.dataset.w + "px" : "")));

  // --- annotation mode ----------------------------------------------------
  const tip = document.createElement("div");
  tip.style.cssText = "position:fixed;z-index:10000;pointer-events:none;background:#000;color:#fff;font:11px/1.4 ui-monospace,monospace;padding:6px 8px;border-radius:5px;display:none;white-space:pre";
  document.body.appendChild(tip);
  let annot = false;
  tools.querySelector("#st-annot").onchange = (e) => { annot = e.target.checked; tip.style.display = "none"; };
  document.addEventListener("mousemove", (e) => {
    if (!annot || tools.contains(e.target)) return;
    const s = getComputedStyle(e.target);
    tip.textContent = `${e.target.tagName.toLowerCase()}${e.target.className && typeof e.target.className === "string" ? "." + e.target.className.split(" ").join(".") : ""}\n` +
      `font ${s.fontSize} / ${s.fontWeight}\ncolor ${s.color}\nbg ${s.backgroundColor}\npad ${s.padding}\nradius ${s.borderRadius}`;
    tip.style.display = "block";
    tip.style.left = Math.min(e.clientX + 14, innerWidth - 260) + "px";
    tip.style.top = Math.min(e.clientY + 14, innerHeight - 110) + "px";
  });

  // --- toast --------------------------------------------------------------
  const toast = document.createElement("div");
  toast.id = "toast";
  document.body.appendChild(toast);
  let t;
  window.toast = (msg) => {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(t);
    t = setTimeout(() => toast.classList.remove("show"), 2200);
  };
})();

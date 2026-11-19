// Spikes 009-011: one Run button walks the loader path of #483 and reports to /report.
const LIVE = "http://127.0.0.1:47632";
const PAIRED = "http://127.0.0.1:47699";
const UNPAIRED = "http://127.0.0.1:47697";
const LOCALHOST = "http://localhost:47699";

// An image load as a response-like object, to compare Safari's rule for images.
function img(url) {
  return new Promise((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve({ status: 200, type: "img", text: async () => "" });
    i.onerror = () => reject(Object.assign(new Error("image did not load"), { name: "ImgError" }));
    i.src = `${url}?t=${Date.now()}`;
  });
}

// The key arrives after "#", which never reaches the host; then it leaves the address bar.
const fromHash = new URLSearchParams(location.hash.slice(1)).get("key");
if (fromHash) {
  localStorage.setItem("spike-key", fromHash);
  history.replaceState(null, "", location.pathname);
}
// localStorage, not sessionStorage: a new tab of this origin keeps the key (run 2 lost it)
const key = localStorage.getItem("spike-key") || "";
const bearer = { Authorization: `Bearer ${key}` };
let token = "";

const STEPS = [
  {
    id: "011-live-nocors", label: "Live daemon: no-cors GET /",
    expect: "resolves, opaque: the request reached the daemon",
    run: () => fetch(`${LIVE}/`, { mode: "no-cors" }),
    pass: (r) => r.response && r.response.type === "opaque",
  },
  {
    id: "011-live-cors", label: "Live daemon: CORS GET /health, no key",
    expect: "TypeError: the daemon sends no CORS answer",
    run: () => fetch(`${LIVE}/health`),
    pass: (r) => r.error === "TypeError",
  },
  {
    id: "009-paired-get", label: "Paired mock: GET /page with the Bearer key",
    expect: "200, page readable and shown below",
    run: () => fetch(`${PAIRED}/page`, { headers: bearer }),
    pass: (r) => r.status === 200 && r.text.includes('id="m"'),
    after: (r) => show(r.text),
  },
  {
    id: "009-paired-nokey", label: "Paired mock: GET /page without the key",
    expect: "401, readable",
    run: () => fetch(`${PAIRED}/page`),
    pass: (r) => r.status === 401,
  },
  {
    id: "009-paired-post", label: "Paired mock: POST /toggle, key + form token",
    expect: "200 toggled",
    run: () => fetch(`${PAIRED}/toggle`, {
      method: "POST", headers: bearer,
      body: new URLSearchParams({ token, adapter: "mail" }),
    }),
    pass: (r) => r.status === 200 && r.text === "toggled",
  },
  {
    id: "009-paired-tas", label: "Paired mock: GET with targetAddressSpace loopback",
    expect: "200, the same as without the option",
    run: () => fetch(`${PAIRED}/page`, { headers: bearer, targetAddressSpace: "loopback" }),
    pass: (r) => r.status === 200,
  },
  {
    id: "009-unpaired-get", label: "Unpaired mock: GET /page with the Bearer key",
    expect: "TypeError: its preflight refuses this origin",
    run: () => fetch(`${UNPAIRED}/page`, { headers: bearer }),
    pass: (r) => r.error === "TypeError",
  },
  {
    id: "010-localhost-get", label: "Paired mock via localhost: GET /page with the key",
    expect: "200 if this browser lets https reach http://localhost",
    run: () => fetch(`${LOCALHOST}/page`, { headers: bearer }),
    pass: (r) => r.status === 200,
  },
  {
    id: "010-img-127", label: "Image from http://127.0.0.1:47699",
    expect: "loads if loopback images are allowed",
    run: () => img(`${PAIRED}/pixel.gif`),
    pass: (r) => r.status === 200,
  },
  {
    id: "010-img-localhost", label: "Image from http://localhost:47699",
    expect: "loads if localhost images are allowed",
    run: () => img(`${LOCALHOST}/pixel.gif`),
    pass: (r) => r.status === 200,
  },
];

// Show the main part of a fetched page, the way the loader would; its scripts never run.
function show(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const main = doc.querySelector("main");
  token = doc.querySelector('input[name="token"]')?.value || "";
  document.getElementById("view").replaceChildren(...(main ? main.childNodes : []));
}

async function perm(name) {
  try {
    return (await navigator.permissions.query({ name })).state;
  } catch (e) {
    return `unsupported (${e.name})`;
  }
}

async function runStep(step, row) {
  const cell = row.querySelector(".got");
  cell.textContent = "waiting (answer the browser prompt if one shows)";
  const t0 = performance.now();
  const r = {};
  try {
    r.response = await step.run();
    r.status = r.response.status;
    r.type = r.response.type;
    r.text = r.response.type === "opaque" ? "" : await r.response.text();
  } catch (e) {
    r.error = e.name;
    r.message = String(e.message).slice(0, 200);
  }
  r.ms = Math.round(performance.now() - t0);
  const ok = Boolean(step.pass(r));
  if (ok && step.after) step.after(r);
  cell.textContent = r.error ? `${r.error}: ${r.message}` : `${r.status} ${r.type}`;
  row.className = ok ? "pass" : "fail";
  return { id: step.id, ok, status: r.status ?? null, type: r.type ?? null,
           error: r.error ?? null, message: r.message ?? null, ms: r.ms };
}

async function runAll() {
  const btn = document.getElementById("run");
  btn.disabled = true;
  const report = {
    at: new Date().toISOString(), secure: window.isSecureContext, key_present: Boolean(key),
    perm_before: { loopback: await perm("loopback-network"), local: await perm("local-network") },
    steps: [],
  };
  for (const step of STEPS) {
    report.steps.push(await runStep(step, document.getElementById(step.id)));
  }
  report.perm_after = { loopback: await perm("loopback-network"), local: await perm("local-network") };
  document.getElementById("perm").textContent =
    `loopback-network: ${report.perm_before.loopback} → ${report.perm_after.loopback}; ` +
    `local-network: ${report.perm_before.local} → ${report.perm_after.local}`;
  const sent = await fetch("/report", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(report),
  }).then((r) => r.ok, () => false);
  document.getElementById("sent").textContent = sent ? "Report sent." : "Report not sent.";
  btn.disabled = false;
}

document.getElementById("rows").replaceChildren(...STEPS.map((s) => {
  const tr = document.createElement("tr");
  tr.id = s.id;
  for (const [cls, text] of [["id", s.id], ["", s.label], ["", s.expect], ["got", "not run"]]) {
    const td = document.createElement("td");
    td.className = cls;
    td.textContent = text;
    tr.append(td);
  }
  return tr;
}));
document.getElementById("keystate").textContent = key ? "Key loaded from the link." : "No key: open the full link.";
document.getElementById("run").addEventListener("click", runAll);

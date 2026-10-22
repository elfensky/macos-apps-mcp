// The dashboard's only script: Copy buttons. The CSP (default-src 'self') forbids
// inline handlers, so the buttons carry the text in a data attribute and one delegated
// listener does the work.
"use strict";

function copyFallback(text) {
  const box = document.createElement("textarea");
  box.className = "copy-buffer";
  box.value = text;
  document.body.appendChild(box);
  box.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  box.remove();
  return ok;
}

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-copy]");
  if (!el) return;
  const text = el.dataset.copy;
  const done = () => {
    const label = el.textContent;
    el.textContent = "Copied";
    setTimeout(() => {
      el.textContent = label;
    }, 1500);
  };
  const clipboard = navigator.clipboard;
  if (clipboard && clipboard.writeText) {
    clipboard.writeText(text).then(done, () => copyFallback(text) && done());
  } else if (copyFallback(text)) {
    done();
  }
});

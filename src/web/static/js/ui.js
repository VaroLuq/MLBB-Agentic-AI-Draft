import { icon } from "./icons.js";

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

/**
 * Tiny element factory. Text is always set via textContent / text nodes,
 * never innerHTML, so user-authored note text can't inject markup.
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Screen-reader announcement without visual noise. */
export function announce(message) {
  const region = $("#sr-live");
  if (!region) return;
  region.textContent = "";
  // A tick between clearing and setting makes repeated identical messages re-announce.
  setTimeout(() => { region.textContent = message; }, 30);
}

export function toast(message, { tone = "info", action = null, onAction = null, timeout = 6000 } = {}) {
  const host = $("#toasts");
  const node = el("div", { class: "toast bevel", role: "status", dataset: { tone } },
    el("span", { class: "t-msg", text: message }),
    action && el("button", {
      class: "btn bevel", type: "button", text: action,
      onclick: () => { onAction?.(); dismiss(); },
    }),
  );
  const dismiss = () => node.remove();
  host.append(node);
  if (timeout) setTimeout(dismiss, timeout);
  return dismiss;
}

const RTF = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
export function relTime(iso) {
  if (!iso) return "never";
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const steps = [[60, "second"], [60, "minute"], [24, "hour"], [30, "day"], [12, "month"], [Infinity, "year"]];
  let value = seconds;
  for (const [size, unit] of steps) {
    if (Math.abs(value) < size) return RTF.format(Math.round(value), unit);
    value /= size;
  }
  return "";
}

export const fmtDate = (iso) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

export const pct = (ratio, digits = 1) => `${(ratio * 100).toFixed(digits)}%`;

export { icon };

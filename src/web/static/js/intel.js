import { api } from "./api.js";
import { $, el, clear, icon, pct } from "./ui.js";
import { portrait } from "./heroes.js";

export function initIntel() {
  $("#intel-refresh").addEventListener("click", loadMeta);
  loadMeta();
}

// ------------------------------------------------------------------ meta
async function loadMeta() {
  const list = $("#intel-list");
  clear(list);
  for (let i = 0; i < 8; i++) {
    list.append(el("li", { class: "intel-row", "aria-hidden": "true" },
      el("span"), el("span", { class: "skel", style: "width:30px;height:30px" }),
      el("span", { class: "skel", style: "height:14px;width:70%" }), el("span", { class: "skel", style: "height:14px;width:42px" })));
  }
  try {
    const { heroes } = await api.meta(8);
    clear(list);
    heroes.forEach((hero, index) => {
      list.append(el("li", { class: "intel-row" },
        el("span", { class: "r-num", "aria-hidden": "true", text: index + 1 }),
        portrait(hero.name, { size: 30 }),
        el("span", { class: "r-name" }, hero.name,
          el("span", { class: "r-sub", text: `Pick ${pct(hero.pick_rate)} · Ban ${pct(hero.ban_rate)}` })),
        el("span", { class: "r-wr", "aria-label": `Win rate ${pct(hero.win_rate)}`, text: pct(hero.win_rate) })));
    });
  } catch (error) {
    clear(list);
    list.append(el("li", {},
      el("div", { class: "banner banner-warn bevel", role: "alert", style: "margin:10px 0 0" }, icon("alert"),
        el("div", { class: "banner-body" }, el("strong", { text: error.message }),
          error.hint && el("p", { text: error.hint }),
          el("div", { class: "banner-actions" }, el("button", { class: "btn bevel", type: "button", onclick: loadMeta }, icon("refresh"), "Retry"))))));
  }
}

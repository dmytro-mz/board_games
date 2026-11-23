// Card faces and backs built as DOM elements (agent cards, black market cards, backs) plus card data.
import { FENCE, ICONS, marketArt, portrait } from "./art.js";
import { h } from "/static/shared/dom.js";

export const AGENTS = {
  double_agent: { name: "Double Agent", animal: "fox", icons: [-1, 6, -1], copies: 6, bg: ["#8fd8c4", "#d9f2e4"] },
  enforcer: { name: "Enforcer", animal: "squirrel", icons: [1, 2, 3], copies: 6, bg: ["#9b78c9", "#f0b9c6"] },
  codebreaker: { name: "Codebreaker", animal: "owl", icons: [0, 0, "win"], copies: 6, bg: ["#5fb6e0", "#cfe9f2"] },
  saboteur: { name: "Saboteur", animal: "raccoon", icons: [-1, -1, -2], copies: 6, bg: ["#3e5fb8", "#9fc0ea"] },
  daredevil: { name: "Daredevil", animal: "wolf", icons: [2, 3, "lose"], copies: 6, bg: ["#ef7e86", "#f8cdb8"] },
  sentinel: { name: "Sentinel", animal: "pigeon", icons: [0, 2, 6], copies: 6, bg: ["#58b8b8", "#d6efe8"] },
  sidekick: { name: "Sidekick", animal: "otter", icons: [4], copies: 1, bg: ["#7fc794", "#f1e7b8"] },
  mole: { name: "Mole", animal: "mole", icons: [-3], copies: 1, bg: ["#c95f94", "#f3b6a8"] },
};
export const AGENT_ORDER = Object.keys(AGENTS);

export const MARKET = {
  distraction_device: { name: "Distraction Device", ongoing: true, text: "When you recruit a <b>Saboteur</b>, move forward instead of backward." },
  watchtower_hq: { name: "Watchtower HQ", ongoing: true, text: "When you recruit an <b>Enforcer</b>, move 2 additional spaces forward." },
  sinister_twin: { name: "Sinister Twin", ongoing: true, text: "When you recruit a <b>Double Agent</b>, move twice as far." },
  supercomputer: { name: "Supercomputer", ongoing: true, text: "When you recruit a <b>Codebreaker</b>, move 3 spaces forward." },
  leader_of_the_pack: { name: "Leader of the Pack", ongoing: true, text: "During the End step, if you have 3 <b>Daredevils</b> in play, you win the game instead of losing it." },
  getaway_car: { name: "Getaway Car", ongoing: true, text: "When you land exactly on either home space, move 3 spaces forward." },
  masterplan: { name: "Masterplan", ongoing: true, text: "During the End step, if you have 7 <u>different</u> agents in play, you win the game." },
  security_system: { name: "Security System", ongoing: true, text: "During the End step, if the opponent is on your home space, you win the game." },
  outpost: { name: "Outpost", ongoing: false, text: "Recruit a <b>Sentinel</b> from your hand." },
  smoke_screen: { name: "Smoke Screen", ongoing: false, text: "Recruit the top card of the agent deck." },
  brainwashing_device: { name: "Brainwashing Device", ongoing: false, text: "Put 1 agent the opponent has in play into your hand." },
  double_trouble: { name: "Double Trouble", ongoing: false, text: "Reveal 2 of the same agent from your hand. Recruit 1 of them." },
  surveillance_truck: { name: "Surveillance Truck", ongoing: false, text: "Move 1 space forward." },
  secret_recruit: { name: "Secret Recruit", ongoing: false, text: "Recruit 1 agent from your hand that is different from the ones you have in play." },
  spycation: { name: "Spycation", ongoing: false, text: "Put 1 agent you have in play into your hand. You may recruit it immediately." },
};

const html = (markup) => {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstChild;
};

function iconEl(value, level) {
  let cls = "ic";
  let content;
  if (value === "win") {
    cls += " win";
    content = html(ICONS.check);
  } else if (value === "lose") {
    cls += " lose";
    content = html(ICONS.cross);
  } else {
    cls += value > 0 ? " pos" : value < 0 ? " neg" : " zero";
    content = value > 0 ? String(value) : value < 0 ? `-${-value}` : "0";
  }
  return h("span", { class: `${cls}${level ? " lit" : ""}` }, content);
}

// An agent card. `level` (1-3) highlights the icon row that matches the copies in play.
export function agentCard(key, { level = 0, size = "", cls = "" } = {}) {
  const a = AGENTS[key];
  if (!a) return cardBack({ size, cls });
  const card = h(
    "div",
    { class: `card agent ${size} ${cls}`.trim(), "data-agent": key, style: { "--bg1": a.bg[0], "--bg2": a.bg[1] } },
    h("div", { class: "art" }),
    h("div", { class: "sign" }, h("span", {}, a.name)),
    h(
      "div",
      { class: "icons" },
      a.icons.map((v, i) => iconEl(v, level && Math.min(level, a.icons.length) === i + 1)),
    ),
  );
  const art = card.firstChild;
  art.innerHTML = FENCE + portrait(a.animal);
  return card;
}

export function cardBack({ size = "", cls = "" } = {}) {
  const el = h(
    "div",
    { class: `card back ${size} ${cls}`.trim() },
    h("div", { class: "back-frame" }, h("div", { class: "back-logo" }, h("span", {}, "AGENT"), h("span", {}, "AVENUE"))),
  );
  el.querySelector(".back-frame").prepend(html(`<div class="back-spy">${ICONS.spy}</div>`));
  return el;
}

export function marketCard(key, { size = "", cls = "" } = {}) {
  const m = MARKET[key];
  if (!m) return marketBack({ size, cls });
  const el = h(
    "div",
    { class: `card market ${m.ongoing ? "ongoing" : "instant"}${m.name.length > 15 ? " long" : ""} ${size} ${cls}`.trim(), "data-market": key, title: `${m.name}: ${m.text.replace(/<[^>]+>/g, "")}` },
    h("div", { class: "m-art" }),
    h("div", { class: "m-title" }, h("span", { class: "m-kind" }), h("span", { class: "m-name" }, m.name)),
    h("div", { class: "m-text" }),
  );
  el.querySelector(".m-art").innerHTML = marketArt(key);
  el.querySelector(".m-kind").append(html(m.ongoing ? ICONS.infinity : ICONS.bolt));
  el.querySelector(".m-text").innerHTML = m.text;
  return el;
}

export function marketBack({ size = "", cls = "" } = {}) {
  const el = h("div", { class: `card market-back ${size} ${cls}`.trim() }, h("div", { class: "mb-frame" }, h("span", {}, "AGENT"), h("span", {}, "AVENUE")));
  el.querySelector(".mb-frame").append(html(`<div class="mb-cart">${ICONS.cart}</div>`));
  return el;
}

// "[double_agent]" in log lines becomes a small coloured chip.
export function richText(text) {
  const parts = [];
  const re = /\[([a-z_]+)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const a = AGENTS[m[1]];
    parts.push(a ? h("span", { class: "chip", style: { "--bg1": a.bg[0], "--bg2": a.bg[1] } }, a.name) : m[0]);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return h("span", {}, parts);
}

export const iconSvg = (name) => html(ICONS[name]);

// The player's hand: cards in the player's own order, click to select, drag to reorder or to drop on the table.
// Pointer events cover mouse, pen and touch. Drop targets are elements with a data-drop attribute.
import { cardEl } from "./cards.js";
import { h } from "./dom.js";

const DRAG_START = 6;

export class HandView {
  constructor({ onToggle, onReorder, onDrop, canDrop }) {
    this.onToggle = onToggle;
    this.onReorder = onReorder;
    this.onDrop = onDrop;
    this.canDrop = canDrop;
    this.el = h("div", { class: "hand", role: "list", "aria-label": "Your hand" });
    this.drag = null;
    this.ids = [];
    this.observer = new ResizeObserver(() => this.fit());
    this.observer.observe(this.el);
  }

  get dragging() {
    return !!this.drag?.active;
  }

  render(cards, { selected, fresh, hidden }) {
    if (this.dragging) return;
    const shown = cards.filter((c) => !hidden.has(c.id));
    this.ids = shown.map((c) => c.id);
    const els = shown.map((c) => {
      const el = cardEl(c, { cls: `${selected.has(c.id) ? "selected" : ""} ${fresh.has(c.id) ? "fresh" : ""}`, attrs: { role: "listitem", tabindex: 0 } });
      el.addEventListener("pointerdown", (e) => this.down(e, c.id, el));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          this.onToggle(c.id);
        }
      });
      return el;
    });
    this.el.replaceChildren(...els);
    this.el.classList.toggle("empty", !els.length);
    this.fit();
  }

  // Overlap cards just enough that the whole hand fits on one row.
  fit() {
    const cards = [...this.el.children].filter((c) => !c.classList.contains("drag-ghost"));
    const n = cards.length;
    if (!n) return;
    const width = this.el.clientWidth - 8;
    const cw = cards[0].offsetWidth;
    const gap = Math.max(4, cw * 0.06);
    const step = n > 1 ? Math.min(cw + gap, (width - cw) / (n - 1)) : cw;
    this.el.style.setProperty("--ml", `${Math.round(step - cw)}px`);
    this.el.classList.toggle("tight", step < cw * 0.6);
  }

  down(e, id, el) {
    if (e.button !== 0 || this.drag) return;
    // Listen on the window: moving the card inside the hand would drop a pointer capture on the element.
    this.drag = { id, el, x0: e.clientX, y0: e.clientY, active: false, target: null, startOrder: [...this.ids] };
    const mine = (ev) => ev.pointerId === e.pointerId;
    const move = (ev) => mine(ev) && this.move(ev);
    const stop = () => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      removeEventListener("pointercancel", cancel);
    };
    const up = (ev) => mine(ev) && (stop(), this.up(ev));
    const cancel = (ev) => mine(ev) && (stop(), this.cancel());
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
    addEventListener("pointercancel", cancel);
  }

  begin(e) {
    const d = this.drag;
    const r = d.el.getBoundingClientRect();
    d.dx = e.clientX - r.left;
    d.dy = e.clientY - r.top;
    d.ghost = d.el.cloneNode(true);
    d.ghost.classList.add("drag-ghost");
    d.ghost.classList.remove("fresh");
    d.ghost.style.setProperty("--cw", `${r.width}px`);
    d.ghost.style.width = `${r.width}px`;
    d.ghost.style.height = `${r.height}px`;
    document.body.append(d.ghost);
    d.el.classList.add("placeholder");
    document.body.classList.add("is-dragging");
    d.active = true;
  }

  move(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.active) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < DRAG_START) return;
      this.begin(e);
    }
    d.ghost.style.transform = `translate(${e.clientX - d.dx}px, ${e.clientY - d.dy}px) rotate(4deg)`;
    const hr = this.el.getBoundingClientRect();
    const inHand = e.clientY > hr.top - 50 && e.clientY < hr.bottom + 30 && e.clientX > hr.left - 30 && e.clientX < hr.right + 30;
    let target = null;
    if (!inHand) {
      const under = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-drop]");
      if (under && this.canDrop(under.dataset.drop, d.id)) target = under;
    }
    if (d.target !== target) {
      d.target?.classList.remove("drop-over");
      target?.classList.add("drop-over");
      d.target = target;
    }
    if (inHand) this.reorderTo(e.clientX);
  }

  reorderTo(x) {
    const d = this.drag;
    const others = [...this.el.children].filter((c) => c !== d.el);
    const rects = others.map((c) => c.getBoundingClientRect());
    let before = null;
    for (let i = 0; i < others.length; i++) {
      // Overlapped cards only show their left strip, so compare with the middle of what's visible.
      const right = i + 1 < others.length ? Math.min(rects[i].right, rects[i + 1].left) : rects[i].right;
      if (x < (rects[i].left + right) / 2) {
        before = others[i];
        break;
      }
    }
    if (before === d.el.nextElementSibling || (before === null && d.el === this.el.lastElementChild)) return;
    const first = new Map(others.map((c) => [c, c.getBoundingClientRect().left]));
    this.el.insertBefore(d.el, before);
    for (const c of others) {
      const dx = first.get(c) - c.getBoundingClientRect().left;
      if (dx) c.animate([{ transform: `translateX(${dx}px)` }, { transform: "none" }], { duration: 140, easing: "ease-out" });
    }
  }

  finish() {
    const d = this.drag;
    this.drag = null;
    document.body.classList.remove("is-dragging");
    if (!d) return null;
    d.ghost?.remove();
    d.el.classList.remove("placeholder");
    d.target?.classList.remove("drop-over");
    return d;
  }

  restore(order) {
    const byId = new Map([...this.el.children].map((c) => [Number(c.dataset.id), c]));
    for (const id of order) if (byId.has(id)) this.el.append(byId.get(id));
  }

  up(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.active) {
      this.finish();
      this.onToggle(d.id);
      return;
    }
    const target = d.target;
    const rect = d.ghost.getBoundingClientRect();
    this.finish();
    if (target) {
      this.restore(d.startOrder);
      this.onDrop(d.id, target.dataset.drop, rect, e);
      return;
    }
    const order = [...this.el.children].map((c) => Number(c.dataset.id));
    if (order.join() !== d.startOrder.join()) {
      this.ids = order;
      this.onReorder(order);
    }
  }

  cancel() {
    const d = this.finish();
    if (d?.active) this.restore(d.startOrder);
  }

  rects() {
    return new Map([...this.el.children].map((c) => [Number(c.dataset.id), c.getBoundingClientRect()]));
  }
}

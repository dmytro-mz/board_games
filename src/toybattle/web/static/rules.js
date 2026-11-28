// The rule book (our own words), opened from the lobby and from the table.

import { h, openDialog } from "/static/shared/dom.js";
import { boardSvg } from "./board.js";
import { icon, troopTile } from "./art.js";

const sample = (kind, side = 0) => side * 24 + kind * 3;

export function showRules(config, terrainKey = null) {
  const kinds = config.kinds || [];
  const terrains = config.terrains || [];
  const current = terrains.find((t) => t.key === terrainKey);
  const tabs = [
    ["basics", "The game"],
    ["troops", "Troops"],
    ["terrains", "Terrains"],
    ["fine", "Fine print"],
  ];
  let tab = "basics";
  const body = h("div", { class: "rules-body" });
  const nav = h("div", { class: "rules-tabs" });
  const sec = (title, ...children) => h("section", {}, h("h3", {}, title), ...children);
  const p = (...c) => h("p", {}, ...c);
  const li = (...c) => h("li", {}, ...c);

  const pages = {
    basics: () => [
      sec(
        "Goal",
        p("Two toy armies face each other across the playroom floor. You win at once when you either:"),
        h("ul", {}, li(h("b", {}, "storm the enemy H.Q."), ": place one of your troops on it, or"), li(h("b", {}, "collect enough medals"), " (the target of the terrain, usually 6 to 8) by taking regions.")),
      ),
      sec(
        "Setting up",
        p("Each army has 24 troops: 8 kinds, 3 of each. Each player shuffles their troops face down into a reserve and puts 4 of them back in the box unseen. The first player (chosen at random) takes 3 troops on their rack, the other player takes 4. Your rack is hidden from your opponent."),
      ),
      sec(
        "Your turn: do one of these",
        h(
          "ol",
          {},
          li(h("b", {}, "Draw 2 troops"), " from your reserve. Your rack holds at most 8; if there is room for only one, or only one troop is left, you draw just one."),
          li(h("b", {}, "Place 1 troop"), " from your rack on a base (or the enemy H.Q.) that is connected to your H.Q., then apply its effect (you may always skip an effect)."),
        ),
      ),
      sec(
        "Where you may place",
        h(
          "ul",
          {},
          li(h("b", {}, "Connected: "), "the base must be linked to your H.Q. by a path, directly or through bases whose top troop is yours. Bases topped by enemy troops break the link."),
          li(h("b", {}, "Empty base: "), "always fine."),
          li(h("b", {}, "On your own troop: "), "fine, whatever the strengths (your stack just gets taller)."),
          li(h("b", {}, "On an enemy troop: "), "only with a strictly stronger troop. The ", h("b", {}, "Jack-in-the-Box"), " (★) is the exception: it may cover any enemy, and any enemy may cover it."),
          li(h("b", {}, "On the enemy H.Q.: "), "any troop may go there when the H.Q. is connected to you, and that wins the game."),
        ),
        p("Only the top troop of a stack counts: it owns the base. Troops underneath stay where they are and come back into play when the top one leaves."),
      ),
      sec(
        "Regions and medals",
        p("The paths divide the board into regions, each worth the medals printed in it. As soon as the top troops on ", h("b", {}, "every"), " base around a region belong to one player, that player takes its medals, for good: later changes don't take them back. Regions are checked after every change on the board, for both players."),
      ),
      sec(
        "End of the game",
        p("The game ends at once when a troop lands on an enemy H.Q., or when a player reaches their medals target. If at the start of your turn you can neither draw nor place a troop, the game ends: the player with more medals wins, and on a tie the player who is stuck loses."),
      ),
      sec("First game", p("The lobby lets the host switch the special bases off: a calmer first game with the troops' effects only. The Castle Field is a good first terrain.")),
    ],
    troops: () => [
      h("p", { class: "sub" }, "Strength decides who may cover whom. Effects are applied right after placing the troop, and are always optional. They only affect visible troops (the top of a stack)."),
      h(
        "div",
        { class: "troop-list" },
        kinds.map((k) =>
          h(
            "div",
            { class: "troop-row" },
            h("div", { class: "pair" }, troopTile(sample(k.kind, 0), { kinds, key: false }), troopTile(sample(k.kind, 1), { kinds, key: false })),
            h("div", {}, h("h4", {}, k.name, h("small", {}, k.kind === 0 ? " · joker" : ` · strength ${k.kind}`)), h("p", {}, h("b", {}, `${k.title}. `), k.text), h("p", { class: "motto" }, `“${k.motto}”`)),
          ),
        ),
      ),
      sec(
        "Order of effects",
        p("A Tin Drummer's extra troop is placed under the normal rules, and its own effect is applied before you carry on (a drummer can call another drummer). When all troop effects are done, the special bases you placed on this turn act, in the order you placed on them."),
      ),
    ],
    terrains: () => [
      h("p", { class: "sub" }, "Each terrain has its own medal target and one kind of special base (the bright ones). A special base acts every time a troop is placed on it, after the troop's own effect."),
      h(
        "div",
        { class: "terrain-list" },
        terrains.map((t) =>
          h(
            "div",
            { class: `terrain-row ${t.key === terrainKey ? "current" : ""}` },
            h("div", { class: "mini-board" }, boardSvg(t, { mini: true })),
            h(
              "div",
              {},
              h("h4", {}, t.name, t.first_game ? h("span", { class: "tag" }, "first game") : null, t.key === terrainKey ? h("span", { class: "tag you" }, "this game") : null),
              h("p", { class: "blurb" }, t.blurb),
              h("p", {}, h("b", {}, "Medals to win: "), t.objective[0] === t.objective[1] ? `${t.objective[0]}` : `Blue ${t.objective[0]}, Red ${t.objective[1]}`, ` (${t.medals} on the board)`),
              h("p", {}, h("b", {}, `${t.effect_title}: `), t.effect_text),
            ),
          ),
        ),
      ),
    ],
    fine: () => [
      sec(
        "Rulings we play by",
        h(
          "ul",
          {},
          li("A Jack-in-the-Box may cover an enemy Jack, and the other way round."),
          li("You may stack your own troops in any order (a 1 on your own 7 is fine), but the new top troop is what the enemy has to beat."),
          li("The Paper Plane flies anywhere except the enemy H.Q., which still needs a connection. On the Station Metal-X it can't land on a repair bay it isn't connected to."),
          li("Repair bays (Station Metal-X) switch off the effect of the troop placed there, nothing else: troops already standing there are not protected from a Slingshot Frog."),
          li("The Magnet Bot discards a random troop from the opponent's rack, pinned or not. The Battlefield buries a random troop that isn't buried yet; it is freed at the end of its owner's next turn and still counts towards the rack limit of 8."),
          li("Troops that go back to a rack (Toy chest, Old trunk) are shown to both players, so your opponent knows they are there."),
          li("The Hot floor moves an enemy troop to any base next to where it stands, whatever the strengths there and whether or not it stays connected. It can't move a troop onto an H.Q."),
          li("On the Tropical Pool the rings and both H.Q.s accept only the strengths printed on them; a Jack-in-the-Box always fits."),
          li("A rack that is already full can't take a troop back; draws stop at 8."),
          li("Medals are checked for both players after every change: a knock-off or a push can hand your opponent a region."),
        ),
      ),
      sec("No take-backs", p("A placed troop stays placed. Think before you click!")),
    ],
  };

  const render = () => {
    nav.replaceChildren(...tabs.map(([key, label]) => h("button", { class: `tab ${tab === key ? "on" : ""}`, onclick: () => ((tab = key), render()) }, label)));
    body.replaceChildren(...pages[tab]());
    body.scrollTop = 0;
  };
  render();
  let close = null;
  close = openDialog(
    h(
      "div",
      { class: "modal rules" },
      h("div", { class: "rules-head" }, icon("fort", "rules-icon", 1), h("h2", {}, "How to play Toy Battle"), h("button", { class: "icon-btn", title: "Close", onclick: () => close() }, "✕")),
      current ? h("p", { class: "rules-now" }, `This game: ${current.name}. ${current.effect_title}: ${current.effect_text}`) : null,
      nav,
      body,
    ),
  );
}

// The rule book: the official rules of Agent Avenue (simple mode, advanced mode, team variant) and every card.
import { AGENTS, AGENT_ORDER, MARKET, agentCard, marketCard } from "./cards.js";
import { h, openDialog } from "/static/shared/dom.js";

const p = (...c) => h("p", {}, ...c);
const b = (t) => h("b", {}, t);
const li = (...c) => h("li", {}, ...c);
const step = (n, title) => h("h4", { class: "rb-step" }, h("span", { class: "rb-num" }, n), title);

function simple() {
  return [
    h("p", { class: "rb-lead" }, "Two spies live next door to each other on Agent Avenue. Each recruits the neighbours as agents to unmask the other. Catch the other spy's meeple before they catch yours!"),
    h("h3", {}, "Setup"),
    h(
      "ul",
      {},
      li("Simple mode uses the board side without black market spaces. The black market cards are not used."),
      li("Each player puts their meeple on the home space of their colour (green or blue). The homes are 7 spaces apart."),
      li("The 38 agent cards are shuffled and everyone gets ", b("4 cards"), ". The rest form the face-down ", b("agent deck"), "."),
      li("The starting player is chosen at random (or by the host)."),
    ),
    h("h3", {}, "Winning the game"),
    p("You try to catch the other meeple before it catches yours. Your progress is where your meeple stands compared to theirs."),
    h("h3", {}, "Cards in hand"),
    p("Whenever you have fewer than 4 agent cards in hand, you draw from the agent deck until you have 4."),
    h("h3", {}, "A turn"),
    step(1, "Play"),
    p("Play 2 cards from your hand to the middle of the table: ", b("1 face up and 1 face down"), ". They must have ", b("different names"), ". Only after playing both do you draw back up to 4 cards."),
    h(
      "p",
      { class: "rb-note" },
      b("Optional: "),
      "before you play, you may discard a card from your hand face down in front of you and draw a new one. You may do this several times in one turn, but only ",
      b("4 times per game"),
      ".",
    ),
    step(2, "Recruit"),
    p("Your opponent must recruit 1 of the 2 cards you played: the face-up one or the face-down one. They put it face up in front of them. You then recruit the other card."),
    p("Then ", b("both players move"), " their meeple. Look at the agent you just recruited and count the agents with that name you have in play, including the new one:"),
    h(
      "ul",
      {},
      li("only 1 → use the card's ", b("1st icon"), " (top);"),
      li("2 → use its ", b("2nd icon"), " (middle);"),
      li("3 or more → use its ", b("3rd icon"), " (bottom). A 4th, 5th or 6th copy counts as the 3rd."),
    ),
    p("Move forward (clockwise) by a positive number, backward (counterclockwise) by a negative one. A zero, or an icon without a number, doesn't move you."),
    h("div", { class: "rb-example" }, agentCard("double_agent", { size: "sm" }), h("div", {}, p("Double Agent: your 1st moves 1 space ", b("backward"), ", your 2nd moves 6 spaces ", b("forward"), ", your 3rd and later move 1 space backward again."))),
    step(3, "End"),
    p("After both meeples moved, check every condition:"),
    h(
      "ul",
      { class: "rb-conds" },
      li(h("span", { class: "rb-tag win" }, "A"), "If your meeple reaches or passes the other meeple, ", b("you win"), "."),
      li(h("span", { class: "rb-tag win" }, "B"), "If you have ", b("3 Codebreakers"), " in play, ", b("you win"), "."),
      li(h("span", { class: "rb-tag lose" }, "C"), "If you have ", b("3 Daredevils"), " in play, ", b("you lose"), "."),
    ),
    p("Otherwise the game goes on and your opponent's turn begins."),
    h("h3", {}, "Running out of cards"),
    p("If nobody won or lost, the agent deck is empty and your opponent has fewer than 2 cards in hand (so they can't play next turn), the game ends: the player who is ", b("closer to catching"), " the other meeple wins."),
    h("h3", {}, "Ties"),
    p("The player whose turn it is (the ", b("active player"), ") wins when both players fulfil a winning condition, both fulfil a losing condition, one player fulfils both a winning and a losing condition, or the cards run out with both meeples equally far from each other."),
    h("h3", {}, "Reminders & clarifications"),
    h(
      "ul",
      {},
      li("The 2 cards you play must have different names. Only if all the cards in your hand have the same name may you play 2 identical cards."),
      li("When the agent deck is empty you can't discard to draw, and you simply stop drawing."),
      li("There is no limit to the cards you may have in play or in hand."),
      li("You can win only in the End step, never during the Recruit step: if your opponent recruits their 3rd Codebreaker, play continues to the End step. If you also catch them that turn, the active player wins."),
      li("If you catch the other meeple but it escapes forward in the same turn, it doesn't count."),
      li("You don't have to land exactly on the other meeple — passing it counts as catching it."),
      li("If the other meeple moves backward onto or behind yours, you have caught it."),
    ),
  ];
}

function advanced() {
  return [
    h("p", { class: "rb-lead" }, "The advanced mode adds the ", b("black market"), ": 15 cards with special abilities you get by landing on the corner spaces of the board."),
    h("h3", {}, "Setup"),
    h(
      "ul",
      {},
      li("Use the board side with the black market spaces in the 4 corners."),
      li("Shuffle the 15 black market cards and put the top 3 face up: the ", b("black market supply"), ". The rest form the face-down black market deck, with a discard pile next to it."),
    ),
    h("h3", {}, "Recruit step"),
    p("After moving forward or backward, if your meeple landed ", b("exactly"), " on a black market space, you ", b("must"), " choose 1 card from the supply. It is replaced immediately with the top card of the black market deck."),
    h(
      "ul",
      {},
      li(b("⚡ Instant abilities"), " are resolved right away, then the card is discarded."),
      li(b("∞ Ongoing abilities"), " stay face up in front of you; the ability is active for the rest of the game."),
    ),
    h("h3", {}, "Clarifications"),
    h(
      "ul",
      {},
      li("Landing exactly on a black market space by moving backward also gets you a card. Passing over one doesn't."),
      li("If you are already on a black market space and an icon doesn't move you (zero or no number), you don't take another card."),
      li("The supply is refilled before the ability is resolved. An ability that can't be performed is ignored."),
      li("A newly taken ongoing ability has no effect on the agent you have just recruited — only from then on."),
      li("Abilities that trigger when you recruit an agent work no matter how you recruit it (also through another ability)."),
      li("Your home space is the starting space of your colour."),
      li("Some ongoing abilities add a way to win in the End step. If that leads to a tie, the active player wins."),
      li("If an instant ability makes you recruit an agent, it goes in front of you as usual and you move again. Landing exactly on another black market space this way gets you another card. Always finish an ability before doing anything else."),
      li("If both meeples land exactly on black market spaces in the same turn, the active player takes a card first and resolves it completely; then the other player takes one."),
      li("If an ability lowers your hand below 4 cards (e.g. Outpost), draw back up to 4. If it raises your hand above 4 (e.g. Brainwashing Device), keep playing normally — you only draw when you have fewer than 4."),
      li("Taking an agent out of play with Brainwashing Device or Spycation doesn't move any meeple. Brainwashing Device can remove a 3rd Codebreaker your opponent recruited that turn, stopping their win."),
    ),
    h("p", { class: "rb-note" }, "Note: the printed card list shows Outpost with the ∞ symbol, but its ability (“Recruit a Sentinel from your hand.”) can only be carried out once, so it is resolved as an instant ability and then discarded. Brainwashing Device is called “Mind Control” in some clarifications of the rule book."),
  ];
}

function team() {
  return [
    h("p", { class: "rb-lead" }, "With 3 or 4 players you play in two teams. Teammates share one meeple and everything they have in play; each has their own hand. They play their turn together and win or lose together."),
    h("h3", {}, "Setup"),
    h(
      "ul",
      {},
      li("With 4 players both teams have 2 players; with 3 players one team has 2 players and the third plays alone."),
      li("Everyone gets 4 agent cards. You may not look at your teammate's cards, nor reveal or describe yours."),
      li("The team variant can be combined with the simple or the advanced mode."),
    ),
    h("h3", {}, "A turn"),
    step(1, "Play"),
    p("Teammates agree who plays first. That player plays 1 card ", b("face up"), "; then the other plays 1 card ", b("face down"), ". They must have different names. Each draws back up to 4 cards."),
    h("p", { class: "rb-note" }, b("Optional: "), "before you play your card (whether your teammate has played or not), you may discard a card face down and draw a new one — ", b("2 times per game"), " for each teammate. A player alone against a team may discard 4 times."),
    p("Here, when a bot is your teammate, you lead: play your card face up, or press ", b("“Let teammate lead”"), " and play face down after them."),
    step(2, "Recruit"),
    p("The players of the opposing team agree which card to recruit: the face-up or the face-down one."),
    step(3, "End"),
    p(b("Running out of cards: "), "if nobody won or lost, the agent deck is empty and an opponent has no cards in hand, the game ends. The team closer to catching the other meeple wins."),
    h("h3", {}, "Clarifications"),
    h(
      "ul",
      {},
      li("If only 1 card is left in the agent deck at the start of the Play step, the teammate who plays face up draws it."),
      li("If all the cards in your hand have the same name as the card your teammate just played face up, you may play an identical card face down."),
      li("If your team's meeple lands exactly on a black market space, agree who takes a card and which. Abilities that use “your hand” use the hand of the teammate who took the card."),
    ),
  ];
}

function cards() {
  const agentRows = AGENT_ORDER.map((key) => {
    const a = AGENTS[key];
    return h("div", { class: "rb-card" }, agentCard(key, { size: "sm" }), h("div", { class: "rb-cap" }, b(a.name), h("span", {}, `${a.copies}×`)));
  });
  const ongoing = Object.keys(MARKET).filter((k) => MARKET[k].ongoing);
  const instant = Object.keys(MARKET).filter((k) => !MARKET[k].ongoing);
  return [
    h("h3", {}, "38 agent cards"),
    p("The icons on the left show how far you move for your 1st, 2nd and 3rd (or later) agent of that name in play. ✓: 3 Codebreakers win the game. ✕: 3 Daredevils lose it."),
    h("div", { class: "rb-grid" }, agentRows),
    h("h3", {}, "15 black market cards (advanced mode)"),
    h("h4", {}, "∞ Ongoing abilities"),
    h("div", { class: "rb-grid market" }, ongoing.map((k) => marketCard(k, { size: "sm" }))),
    h("h4", {}, "⚡ Instant abilities"),
    h("div", { class: "rb-grid market" }, instant.map((k) => marketCard(k, { size: "sm" }))),
  ];
}

const TABS = [
  ["simple", "Simple mode", simple],
  ["advanced", "Advanced mode", advanced],
  ["team", "Team variant", team],
  ["cards", "Cards", cards],
];

export function showRules(initial = "simple") {
  let close = null;
  const body = h("div", { class: "rb-body" });
  const tabs = h("div", { class: "rb-tabs", role: "tablist" });
  const select = (key) => {
    const tab = TABS.find((t) => t[0] === key) || TABS[0];
    body.replaceChildren(...tab[2]());
    body.scrollTop = 0;
    for (const btn of tabs.children) btn.classList.toggle("on", btn.dataset.tab === tab[0]);
  };
  for (const [key, label] of TABS) tabs.append(h("button", { class: "rb-tab", "data-tab": key, role: "tab", onclick: () => select(key) }, label));
  close = openDialog(
    h(
      "div",
      { class: "modal rulebook" },
      h("div", { class: "rb-head" }, h("h2", {}, "Rule book"), h("button", { class: "icon-btn", title: "Close", onclick: () => close() }, "✕")),
      tabs,
      body,
    ),
  );
  select(initial);
}

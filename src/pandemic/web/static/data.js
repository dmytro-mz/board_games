// Static game data for the client. City names, colors and connections come from /api/config (initData).

export const COLORS = { blue: "#3d8bff", yellow: "#f2c12e", black: "#2a2f3a", red: "#e8413b" };
export const INK = { blue: "#fff", yellow: "#231a00", black: "#fff", red: "#fff" };
export const DNAME = { blue: "Blue", yellow: "Yellow", black: "Black", red: "Red" };
export const DCOLS = ["blue", "yellow", "black", "red"];
export const SHAPES = { blue: "circle", yellow: "triangle", black: "square", red: "diamond" };

export const W = MAP.W;
export const H = MAP.H;
const PAD_L = 64;
const PAD_R = 20; // ocean margins, so routes across the Pacific seam stay visible
export const FULL = { x: -PAD_L, y: 0, w: W + PAD_L + PAD_R, h: H };
export const HOME = { x: -PAD_L, y: 70, w: W + PAD_L + PAD_R, h: 620 }; // crops the empty polar bands

const COUNTRY = {
  sf: "United States", chi: "United States", mon: "Canada", ny: "United States", was: "United States", atl: "United States",
  lon: "United Kingdom", mad: "Spain", par: "France", ess: "Germany", mil: "Italy", stp: "Russia",
  la: "United States", mex: "Mexico", mia: "United States", bog: "Colombia", lim: "Peru", san: "Chile",
  bue: "Argentina", sao: "Brazil", lag: "Nigeria", kin: "DR Congo", joh: "South Africa", kha: "Sudan",
  alg: "Algeria", cai: "Egypt", ist: "Turkey", mos: "Russia", bag: "Iraq", riy: "Saudi Arabia",
  teh: "Iran", kar: "Pakistan", del: "India", mum: "India", che: "India", kol: "India",
  bei: "China", seo: "South Korea", tok: "Japan", sha: "China", osa: "Japan", tai: "Taiwan",
  hk: "China", bkk: "Thailand", man: "Philippines", hcm: "Vietnam", jak: "Indonesia", syd: "Australia",
};

export const CITIES = {};
export const ADJ = {};
export const EDGES = [];
export const EVENTS = {};
export const CFG = { infectionRate: [2, 2, 2, 3, 3, 4, 4], hand: 7, stations: 6, outbreaks: 8, cubes: 24, startingHand: { 2: 4, 3: 3, 4: 2 } };

export function initData(config) {
  for (const c of config.cities) {
    const [x, y] = MAP.cities[c.id];
    CITIES[c.id] = { id: c.id, name: c.name, color: c.color, country: COUNTRY[c.id] || "", x, y };
    ADJ[c.id] = c.adj;
  }
  EDGES.length = 0;
  for (const c of config.cities) for (const b of c.adj) if (c.id < b) EDGES.push([c.id, b]);
  for (const e of config.events) EVENTS[e.key] = { name: e.name, text: e.text };
  CFG.infectionRate = config.infection_rate;
  CFG.hand = config.limits.hand;
  CFG.stations = config.limits.stations;
  CFG.outbreaks = config.limits.outbreaks;
  CFG.cubes = config.limits.cubes;
  CFG.startingHand = config.starting_hand;
}

export const ROLES = {
  medic: {
    name: "Medic",
    color: "#ff9a3c",
    short: "Treat removes all cubes of a colour",
    abilities: [
      "Treat Disease removes <b>all</b> cubes of one colour from your city, not just 1.",
      "Once a disease is cured, its cubes are removed from your city automatically, with no action needed. While you stay there, new cubes of that colour can’t be placed.",
    ],
    example: "Blue is cured. The Medic drives into Chicago, which has 2 blue cubes, and both disappear for free.",
    bonus: { treat: "Medic: removes all" },
  },
  scientist: {
    name: "Scientist",
    color: "#cdbcff",
    short: "Cures with 4 cards, not 5",
    abilities: ["You need only <b>4</b> cards of the same colour to Discover a Cure, instead of 5."],
    example: "With Bangkok, Tokyo, Shanghai and Seoul at a research station, the Scientist cures red.",
    bonus: { cure: "Scientist: 4 cards" },
  },
  researcher: {
    name: "Researcher",
    color: "#c8935a",
    short: "Can give any city card",
    abilities: [
      "When you Share Knowledge, you may give <b>any</b> city card from your hand. It doesn’t have to match the city you are in.",
      "A teammate in your city can also take any one of your city cards.",
    ],
    example: "In Madrid, the Researcher hands the Delhi card to the Medic.",
    bonus: { share: "Researcher: any card" },
  },
  ops: {
    name: "Operations Expert",
    color: "#ff7eb6",
    short: "Builds stations without a card",
    abilities: [
      "Build a research station in your city <b>without</b> discarding a card.",
      "Once per turn, from a research station, move to any city by discarding any city card.",
    ],
    example: "In Lagos, the Operations Expert builds a station without needing the Lagos card.",
    bonus: { build: "Ops Expert: no card" },
  },
  dispatcher: {
    name: "Dispatcher",
    color: "#b07cff",
    short: "Moves other players’ pawns",
    abilities: [
      "Move any other pawn as if it were your own (ask its owner first).",
      "As an action, move any pawn to a city that already has another pawn.",
    ],
    example: "The Dispatcher moves the Medic straight to the Scientist in Hong Kong.",
    bonus: {},
  },
  quarantine: {
    name: "Quarantine Specialist",
    color: "#f0a6ff",
    short: "Blocks infection around her",
    abilities: ["No disease cubes can be placed, and no outbreaks can happen, in your city and every city connected to it."],
    example: "Parked in Tehran, she protects Tehran, Moscow, Baghdad, Karachi and Delhi.",
    bonus: {},
  },
  planner: {
    name: "Contingency Planner",
    color: "#ffd6a5",
    short: "Reuses a discarded event",
    abilities: [
      "As an action, take an event card from the player discard pile and store it on your role card (one at a time).",
      "When you play the stored event, remove it from the game.",
    ],
    example: "He takes back the discarded Forecast and plays it before the next Epidemic.",
    bonus: {},
  },
};

export const DIFFS = [
  { n: 4, name: "Introductory", desc: "Learn the game. Plenty of breathing room." },
  { n: 5, name: "Standard", desc: "The normal challenge for experienced teams." },
  { n: 6, name: "Heroic", desc: "Epidemics come fast. Every action counts." },
];

export const SPEEDS = [
  { key: "slow", name: "Slow", desc: "Time to follow every bot move." },
  { key: "normal", name: "Normal", desc: "A relaxed pace." },
  { key: "fast", name: "Fast", desc: "Bots barely pause." },
];

export const LOSS = {
  outbreaks: "The 8th outbreak ended the game",
  cubes: "A disease ran out of cubes",
  deck: "The player deck ran out",
};

// Client state shared by every module, and read-only accessors on the latest server state.

export const S = {
  config: { bots: [], reactions: [], max_seats: 4, min_seats: 2, public_url: null, lan_url: null },
  token: null,
  name: "",
  code: null,
  ws: null,
  retry: 0,
  reconnectTimer: null,
  connected: false,
  fatal: null,
  me: null,
  log: [],
  state: null,
  ui: freshUi(),
};

export function freshUi() {
  return {
    mode: null, // drive | direct | charter | shuttle | dispatch | airlift | grant
    pawn: null, // the pawn the Dispatcher moves (null: their own)
    airlift: null, // the pawn an Airlift moves
    flow: false, // an event card is being played: hold back the forced dialogs
    passArm: false,
    feed: [],
    feedQueue: [],
    holding: false,
    fx: {},
    unread: 0,
    turnEvents: [],
    infectPanel: null,
    prevT: null,
    forced: null,
    overShown: false,
  };
}

export const st = () => S.state;
export const g = () => S.state?.game || null;
export const mySeat = () => S.state?.you.seat ?? null;
export const isHost = () => S.state && S.state.host === S.me;
export const seatName = (i) => S.state?.seats[i]?.name || "?";

export function inviteUrl() {
  const base = S.config.public_url || S.config.lan_url || location.origin;
  return `${base.replace(/\/$/, "")}/r/${S.code}`;
}

export function players() {
  const state = S.state;
  const game = state?.game;
  if (!game) return [];
  return game.players.map((p, i) => ({
    i,
    name: state.seats[i]?.name || `Player ${i + 1}`,
    bot: state.seats[i]?.bot,
    connected: state.seats[i]?.connected,
    autoplay: state.seats[i]?.autoplay,
    member: state.seats[i]?.member,
    role: p.role,
    at: p.location,
    hand: p.hand,
    count: p.count,
    stored: p.stored,
  }));
}

// The seat the screen is centred on: your own, or the player on turn when you are watching.
export const viewSeat = () => mySeat() ?? g()?.current ?? 0;
export const me = () => (mySeat() == null ? null : players()[mySeat()]);
export const over = () => !!g()?.result;

// True when you are the one the game waits for in the action phase.
export function myTurn() {
  const game = g();
  const seat = mySeat();
  return !!game && seat != null && !game.result && game.current === seat && game.step === "actions" && game.waiting_for === seat;
}

export const actionsLeft = () => g()?.actions_left ?? 0;
export const infectionRate = () => g()?.infection_rate ?? 2;
export const cubesAt = (id) => g()?.cubes[id] || {};
export const cubeCount = (id) => Object.values(cubesAt(id)).reduce((a, b) => a + b, 0);
export const stations = () => g()?.stations || [];
export const cures = () => g()?.cures || { blue: "none", yellow: "none", black: "none", red: "none" };
export const need = (role) => (role === "scientist" ? 4 : 5);

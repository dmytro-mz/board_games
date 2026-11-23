// What every game client shares with the platform (served at /static/shared/platform.js).
//
// A game runs at /g/<key>/r/CODE, inside the room page's iframe (or on its own, e.g. in browser checks).
// The room page and all games use one identity: the same token and name in localStorage, so the player is the
// same person in the room and at every game table.

export const TOKEN_KEY = "bg.token";
export const NAME_KEY = "bg.name";

// URL prefix of a game's server routes, from its own module URL: /g/<key>/static/app.js -> "/g/<key>/".
export const gameBase = (moduleUrl) => new URL("..", moduleUrl).pathname;

export function socketUrl(base, code) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}${base}ws/${code}`;
}

// The room code of a game page (/g/<key>/r/CODE), or null.
export function roomCode() {
  const match = location.pathname.match(/\/r\/([A-Za-z0-9]{4,8})\/?$/);
  return match ? match[1].toUpperCase() : null;
}

// "Leave table" in a game leaves the whole room: back to the platform's start page.
export function leaveRoom() {
  window.top.location.href = "/";
}

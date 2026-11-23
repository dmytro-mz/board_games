// Messages to the room. The server checks every request and answers with a new state or an error.
import { S } from "./store.js";
import { toast } from "./ui.js";

export function send(msg) {
  if (S.ws && S.ws.readyState === WebSocket.OPEN) {
    S.ws.send(JSON.stringify(msg));
    return true;
  }
  toast("Not connected. Reconnecting…", true);
  return false;
}

// Game actions in order (a long drive is one request per step).
export function act(...actions) {
  S.ui.holding = false; // the server ends a hold once the game moves on
  for (const action of actions) if (!send({ type: "action", action })) return;
}

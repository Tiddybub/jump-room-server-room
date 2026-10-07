# The Jump Room server room

One small always-on process that runs the online server of every game on the hub, so nobody has
to put a game on Render AND on the Jump Room. Upload the game to the Jump Room; if the zip has a
`server/` folder, this room pulls that folder out and runs it, and the Jump Room points the game at it.

The Jump Room itself is on Netlify, which runs page requests only (nothing can stay running there),
so this room lives on Render's free Docker tier: the same place Alex's Rift Rumble server ran, but
one box for everybody's servers instead of one per game.

| File | What it is |
|---|---|
| `index.mjs` | The room: reads `/api/catalog`, finds `server/` folders in the stored zips, starts them, passes WebSockets through at `/<person>/<game>` |
| `Dockerfile` | node 24 + a headless Godot 4.7.2, nothing else |
| `render.yaml` | Render Blueprint: free web service, health check on `/health` |

## What a game needs in its zip

- `server/Dockerfile` whose `COPY` lines name the files the server needs and whose `CMD` starts it
  (Rift Rumble: `node gateway.mjs`, which starts Godot itself), **or** just `server/server.gd`
  (a `SceneTree` script) and the room runs
  `godot --headless --script res://server/server.gd` with `server/` and `scripts/` copied in.
- The server listens on the port in the `PORT` environment variable, on `127.0.0.1`
  (`BIND_ADDRESS` is set to that too).
- The browser build reads its server address from a small JSON file next to its `index.html` with
  a `server_url` field (Rift Rumble: `web/rift-config.json`). The Jump Room's player rewrites that
  field to `wss://<room>/<person>/<game>` on the way through, so the game never needs to know where
  the room is. A downloaded Windows build keeps whatever address is in its own config.
- `RUN`, `FROM`, `USER`, `EXPOSE` lines in the Dockerfile are ignored: the room's image already has
  node and Godot. A literal `/app` (the Dockerfile's `WORKDIR`) inside the copied scripts is
  replaced with the folder the server really runs from.

## Setting it up (once)

1. Put this folder in a GitHub repository (the three files above are enough).
2. Render dashboard > New + > Blueprint > that repository > Apply. Free plan. It builds in a few
   minutes (the image downloads Godot) and comes up at `https://<name>.onrender.com`.
3. On Netlify, give the hub that address and redeploy:

   ```
   netlify env:set SERVER_ROOM_URL https://<name>.onrender.com
   netlify deploy --prod --dir=site --functions=netlify/functions
   ```

From then on every game card with a `server/` folder shows **online server · hosted here**, and
`/health` on the room lists what is running.

## Day to day

- A new build uploaded to the hub replaces the running server as soon as nobody is connected to it
  (a build that arrives mid-match waits; `/status` shows `waiting`).
- Render's free box sleeps after 15 idle minutes; the Jump Room's play page pings the room the moment
  a game with a server opens, so it is usually awake before the game has finished loading.
- Rooms live in memory. A restart ends matches in progress, same as on Render.
- Logs: Render dashboard > the service > Logs. Every line is prefixed with the game (`[alex/rift-rumble]`).

## Running it on a PC for a test

```
set PORT=10700
set GODOT_BIN=C:\Users\timmy\Tools\Godot\Godot_v4.7.2-stable_win64_console.exe
set GAMES=alex/rift-rumble
node index.mjs
```

Then `curl http://127.0.0.1:10700/status`. `GAMES` limits the room to the games named (comma
separated); leave it unset to run everything with a server folder.

# Resuming UI preview work

Quick reference for coming back to this later. Two commands, every time.

## Every time

1. Open Terminal.
2. Run:
   ```
   cd ~/CascadeProjects/vitruvity33/tablescope
   ./ux-design/start-preview.sh
   ```
   (This just `cd`s into `web-ui` and runs `npm run dev` — the script exists
   so you don't have to remember the path.)
3. Wait for it to print `Ready` / a `localhost:3000` line.
4. Open `http://localhost:3000/projects` in your browser.
5. Check the browser console for `[dev-mock] fetch interceptor active` — if
   you see that line, the local mock layer is working and you should see the
   fake "API Costs" project and be able to create new ones.
6. Leave that terminal window open and running while you work. Ctrl+C in it
   to stop the server when you're done.

## If you're pulling in new work from Devin

Before step 2 above (or in a second terminal tab while the server runs —
either is fine, Fast Refresh picks it up automatically):
```
cd ~/CascadeProjects/vitruvity33/tablescope
./ux-design/pull-latest.sh <devin's-branch-name>
```

## One-time things that are already done (nothing to do unless something's broken)

- `web-ui/node_modules` — installed. If `npm run dev` complains about missing
  packages, run `npm install` in `web-ui` again.
- `web-ui/.env.local` — already created, gitignored, turns on the mock layer.
  If it's ever missing, recreate it with one line: `NEXT_PUBLIC_MOCK_API=1`.
- Login/session — handled automatically by the mock layer now; you don't
  need to paste anything into the browser console anymore.

## The static flow-sketch prototype (optional, secondary now)

If you just want to sketch a flow without running the full app:
```
cd ~/CascadeProjects/vitruvity33/tablescope
npx live-server --open=/prototype-ux.html
```
This is the older, disconnected mockup — useful for a fast idea sketch, but
the real preview (above) is what your Devin changes actually show up in.

# Final Fantasy XIV

Madeira signs in to Square Enix itself and starts `game\ffxiv_dx11.exe` with the
session, the way Square Enix's launcher does (`app/Madeira/SwiftFFXIV/FFXIVLogin.swift`,
`app/Madeira/FFXIVLaunch.swift`). Installing and updating the game stays with Square
Enix's launcher for now.

## Setting it up

1. Settings › PC game launchers › Final Fantasy XIV launcher › **Download installer**
   fetches `ffxivsetup.exe` from `gdl.square-enix.com` and adds "Install Final
   Fantasy XIV launcher" to the library. Play it and finish the installer.
2. **Add to library** adds the launcher (`boot\ffxivboot.exe`, for updates) and,
   once the game is installed, the game (`game\ffxiv_dx11.exe`).
3. Open the launcher once to download the game and accept Square Enix's terms.

## Playing

Play on the game asks for the Square Enix ID, the password and the one-time password
(when the account has one). Madeira then:

1. reads `_STORED_` from the login page (`ffxiv-login.square-enix.com/oauth/ffxivarr/login/top`);
2. posts it with the ID and passwords to `login.send`, which answers with the session,
   the region and the account's newest expansion;
3. registers the session at `patch-gamever.ffxiv.com` with the installed versions
   (`boot\ffxivboot.ver`, `game\ffxivgame.ver`, `game\sqpack\exN\exN.ver`) and the
   boot programs' sizes and SHA-1s;
4. starts the game with `DEV.TestSID=<session>` and the rest of the launcher's
   arguments, for this launch only.

When the server lists updates (or answers 409 for an outdated boot folder), Play
says so: open the Final Fantasy XIV launcher from the library to update, then play
again.

The ID is kept for next time. The password is kept only with **Remember password on
this device** on, as a Keychain item for this device only (not synchronised). The
one-time password, the password and the session never go into a log.

## Not supported yet

- Steam accounts: their sign-in needs a Steam ticket. Madeira says so and stops.
- Free trial accounts (`isft=1`).
- Patching inside Madeira (ZiPatch). The official launcher's window is Internet
  Explorer's engine (mshtml); if it cannot run in Madeira's Wine, Madeira's own
  patcher is the next step.

## Recommended settings

| Program | List |
|---|---|
| `boot\ffxivboot.exe` | `ffxiv-launcher`: the Wine desktop, standard line |
| `ffxivsetup.exe` | `ffxiv-setup`: the Wine desktop, standard line |

The game has no list of its own yet. None of this is device-tested yet.

Written from the protocol XIVLauncher (goatcorp, GPL-3.0) documents; no code is
taken from it. Tests: `tests/host/check-ffxiv-login.py`.

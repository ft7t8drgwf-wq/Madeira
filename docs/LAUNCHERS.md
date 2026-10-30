# Publishers' launchers

Some publishers' games only start with the publisher's own launcher running:
Ubisoft Connect, Battle.net and the Rockstar Games Launcher. None of them has an
open client Madeira could speak for, as it does for Steam, Epic and GOG, so
Madeira runs the real launcher in the Wine desktop
(`app/Madeira/LauncherSupport.swift`).

## Settings › PC game launchers

- **Download installer** fetches the publisher's installer from its own HTTPS
  address into `drive_c\Madeira Downloads` and adds it to the library as
  "Install <launcher>". Nothing is downloaded until you tap it.
- Play that entry and finish the installer in the Wine desktop.
- **Add to library** then adds the installed launcher. Sign in in the
  launcher's own window; Madeira never sees the password.
- **Repair** (Ubisoft Connect) runs the Ubisoft repairs below by hand.

An installer you downloaded yourself works the same way: add it to the library
as any program. Madeira recognises it by its file name.

## Recommended settings

`GameRecommendations.swift` recognises each launcher by its program in its own
folder, and each installer by the name it downloads with:

| Program | List |
|---|---|
| `Ubisoft Game Launcher\UbisoftConnect.exe`, `upc.exe`, `Uplay.exe` | `ubisoft-connect` |
| `UbisoftConnectInstaller.exe` | `ubisoft-connect-setup` |
| `Battle.net\Battle.net Launcher.exe`, `Battle.net.exe` | `battle-net` |
| `Battle.net-Setup.exe` | `battle-net-setup` |
| `Rockstar Games\Launcher\Launcher.exe` | `rockstar-launcher` (125hz) |
| `Rockstar-Games-Launcher.exe` | `rockstar-launcher-setup` (125hz) |
| `boot\ffxivboot.exe` | `ffxiv-launcher` |
| `ffxivsetup.exe` | `ffxiv-setup` |

Every one of them starts in the Wine desktop with Windows services first (the
lists' `launchMode` and `startServices`): the launchers install services and use
out-of-process COM. The 64-bit launchers' windows are Chromium (CEF), so the Battle.net
and Rockstar lists take the lines Social Club and Steam's web helper need: Social Club layout 2
(`env.MADEIRA_SC_PA_POOLS = 2`, room for Chromium 128+'s three 32 GB
reservations), the JIT pool lines for libcef.dll, pure-x64 images uncopied, and
the swap file for the web helper's idle pages. Ubisoft Connect's and Battle.net's
lists have no release delay (`MADEIRA_FREE_DELAY_MS`): Chromium's allocator
reserves, releases and reserves again. The installers get the standard line
only.

Ubisoft Connect is 32-bit: UbisoftConnect.exe, upc.exe and UplayWebCore.exe each
need a 4 GB window, so its list (version 2) has none of the 64-bit Chromium lines.
With them, build 48's upc.exe found no window and the client never opened. The
extra windows spill into the range the 64-bit Chromium layout would take.

Battle.net's list also turns off Windows' location service
(`env.WINEDLLOVERRIDES = locationapi=d`), which the client stops on under Wine.

The Ubisoft Connect and Battle.net lists are not device-tested yet.

## Library sections

Each launcher has its own library section, like Steam's and GOG's
(`app/Madeira/LauncherGames.swift`), shown once the launcher is installed or added:

- the launcher and the games you added from its folders (they leave Other games);
- an **Add** card when the launcher is installed but not in the library yet;
- the games it installed that are not in the library yet, each with **Add**:
  Ubisoft's `games` folder, Rockstar's game folders, Blizzard's game folders,
  Final Fantasy XIV's game. Add picks the folder's one program (helpers aside), or
  the one named like the folder; otherwise it asks for + instead.

Final Fantasy XIV's launcher is in the same section, for installing and updating the
game only: its window is Internet Explorer's engine, so its lists are the Wine
desktop and the standard line. The game signs in through Madeira (docs/FFXIV.md).

## Ubisoft repairs

Older Ubisoft games (Assassin's Creed and others) look for `Uplay.exe`, the
client's install folder in the registry (often from a 32-bit game), or start the
client through `uplay://`. Before every library start and every Madeira Dock
start, while no session runs, Madeira:

- makes `Uplay.exe` and `upc.exe` links beside the client when missing (a real
  file of that name stays; a link a client update left dangling is made again);
- writes `HKLM\Software\Ubisoft\Launcher` `InstallDir` in both registry views;
- registers `uplay://` and `ubisoft-connect://` in the user's classes.

Nothing happens without Ubisoft Connect installed, and nothing twice. The
registry goes through `SteamInstallRegistry` (a `.madeira-bak` copy is kept
before the first change). A Ubisoft game bought on Steam still needs Ubisoft
Connect installed and signed in.

Based on SaimSuhailQu's launcher support (willfaust/Madeira #260, not merged).
Tests: `tests/host/check-launcher-support.py`,
`tests/host/check-game-recommendations.py`.

# GOG

Madeira can sign in to GOG, list the account's Windows games, download them with
the DLC the account owns, and start them through Wine and FEX. It does not
install GOG Galaxy. The protocol work follows Heroic's
[gogdl](https://github.com/Heroic-Games-Launcher/heroic-gogdl).

## Source

- `app/Madeira/SwiftGOG/GOGAPI.swift`: sign-in, the device-only Keychain token
  item, the library listing, owned ids, covers, builds, manifests and signed CDN
  addresses.
- `app/Madeira/SwiftGOG/GOGDownloader.swift`: the depot file list, chunk checks,
  install, update, repair, renewed CDN addresses, and the resume journal. It
  depends on no other store's code.
- `app/Madeira/GOGLibrary.swift`: the account, installed records, download
  queue, and the play task from `goggame-<id>.info`.
- `app/Madeira/GOGGames.swift`: sign-in, library, download, game-detail and
  settings views.

## Account and games

Sign in under Settings > GOG, or from the GOG section of the library. Madeira
shows GOG's own login page. When it finishes, GOG redirects to
`embed.gog.com/on_login_success` with a one-use code, which Madeira trades for an
access token and a refresh token. Tokens stay in the Keychain, for this device
only. If the web view cannot finish a login, sign in in Safari and paste the
final page's address.

The library lists the account's games that work on Windows. Covers come from
GOG's game database. GOG games are DRM-free: they play without a sign-in, and a
sign-in is only needed to download and update.

`env.MADEIRA_GOG = 0` hides everything GOG. Installed GOG games then stay in the
library entries but have no GOG section.

## A download

Madeira asks GOG's content system for the newest Windows build on the default
branch (generation 2). It installs the game's depots and those of DLC the account
owns, in English when the game has it, else the first language it lists, and
the 64-bit depots when a build has both. GOG's support files (installer scripts)
are left out.

Installs use `drive_c/GOG Games/<folder>`. Paths are checked against that
folder. Every chunk is checked by the MD5 of its compressed bytes and of its
contents, and a file with an MD5 is checked as a whole. Each file is written to
a temporary name and then renamed into place. Free space is checked before
any chunk is fetched. Pause keeps finished files, and a journal lets Resume skip
them. Signed CDN addresses are renewed when GOG stops accepting them. Update
keeps files whose checksum is unchanged and deletes files the new build no longer
has. Repair checks every chunk of every installed file. Cancel removes a partial
first install; it stops an update or repair without deleting the game.

In the background a download runs for the grace period iOS allows, then pauses
cleanly and continues when Madeira is active again. Downloads also pause for a
game session.

When a download finishes, Madeira reads the build's `goggame-<id>.info`. Its
primary file task names the program, its arguments and its working folder,
which become the game's library entry. A build without that file uses the
folder's only program. Otherwise the install stops with a message to add the
game by hand.

## Not supported yet

- Generation 1 builds, which some older games still have. Madeira says so
  instead of downloading.
- GOG Galaxy features: cloud saves, achievements, and online services that need
  the Galaxy client.
- GOG's redistributable installers (DirectX, Visual C++). Madeira's own Visual
  C++ runtime covers the common case.
- Delta patches. An update downloads changed files whole.
- A language or branch picker.

## Checks

`python3 tests/host/check-gog-store.py` runs static checks: licence headers,
every GOG source in the Xcode project, the device-only Keychain item, no token or
code in a log line, GOG entries kept out of Other games, and the settings
catalog entry, the Game details page, and that the GOG code uses no Epic store
types. The Swift code has not been compiled on this branch. It needs
the app build and a device test of sign-in, listing, install, Play,
pause/resume, update, repair and uninstall.

## Credits

gogdl's protocol and format work is GPL-3.0, by the Heroic Games Launcher
contributors. Relevant sources include `gogdl/auth.py`, `gogdl/api.py`,
`gogdl/dl/dl_utils.py`, `gogdl/dl/objects/v2.py`, `gogdl/dl/managers/v2.py`,
`gogdl/dl/workers/task_executor.py` and `gogdl/launch.py`. No gogdl code is
included. The app uses Apple frameworks and adds no dependency.

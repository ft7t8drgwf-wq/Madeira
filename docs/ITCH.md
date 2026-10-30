# itch.io

Madeira lists the games you bought or claimed on itch.io and installs their
Windows downloads, the same way as the GOG store (docs/GOG.md).

- `app/Madeira/SwiftItch/ItchAPI.swift`: itch.io's server API at
  `api.itch.io`, the calls the itch app makes through go-itchio (MIT):
  `GET /profile`, `/profile/owned-keys`, `/games/<id>/uploads?download_key_id=`
  and `/uploads/<id>/download`. The API key goes in the `Authorization` header.
- `app/Madeira/SwiftItch/ItchArchive.swift`: the zip unpacker.
- `app/Madeira/ItchLibrary.swift`: the account's games, downloads and installs.
- `app/Madeira/ItchGames.swift`: the library section, download sheet, Game
  details section, Settings › itch.io and the sign-in sheet.

## Signing in

itch.io has no sign-in Madeira can use without registering an app with it, so
Madeira signs in with an API key: Settings › itch.io › Sign in opens
<https://itch.io/user/settings/api-keys>, where **Generate new API key** makes
one; paste it into Madeira. Madeira keeps it only once itch.io accepts it, in
this device's Keychain (`madeira.itch.key`, this device only, not synchronised).
Sign out removes it; deleting the key on itch.io stops it everywhere. Installed
games keep playing: itch.io games need no sign-in to start.

## What installs

itch.io decides ownership: the list is the account's owned keys, and a game's
files are only listed and served for its download key. Madeira lists games and
tools with a Windows build (or no platforms listed), and installs one upload:

1. the game's own Windows file (not a soundtrack, a preorder, or a demo when
   the full game is there);
2. a 64-bit or any-architecture file before a 32-bit one;
3. a `.zip` before an `.exe` (a butler build counts as a zip), then the biggest.

A `.zip` unpacks into `C:\itch\<title>`; a lone `.exe` goes there as it is
(when it is an installer, Play runs it). Other archives (`.rar`, `.7z`) are not
supported yet; the sheet says so. The unpacker reads the archive a piece at a
time (ZIP64 too), checks every CRC-32, and only replaces the install folder once
every file is in. Names that leave the folder, absolute names, encrypted entries,
symbolic links and two names that differ only in case stop it.

The program that starts the game is the first `[[actions]]` path of the game's
`.itch.toml`, else the folder's only program within three levels (uninstallers,
crash handlers and redistributables aside), else the one named like the game,
else the one nearest the top. When none is clear, the download fails with a note
to add the program by hand.

Downloads pause for a game session and in the background (iOS's grace period),
and resume where they stopped. An update is offered when itch.io's chosen upload
or its build changes. `env.MADEIRA_ITCH = 0` turns the store off.

Tests: `tests/host/check-itch-store.py`.

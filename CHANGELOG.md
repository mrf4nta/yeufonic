# Changelog

Versions are git tags on `main`. The number lives in `VERSION`, which is copied into the
app image and shown in the header, so a running container can be identified at a glance.

**Every deploy bumps `VERSION`; only a release gets a tag.** The number in the header says
which build is running, so it moves with each change deployed. A tag, an entry here and a push are
for a milestone worth naming, and are cut only when asked for — not for every update.

To deploy a change:

1. Merge to `main`, bump `VERSION`, redeploy.

To cut a release:

1. Add an entry here, newest first.
2. `git tag -a vX.Y.Z -m "..."`
3. `git push origin main --tags`   (homer only, unless GitHub is wanted)
4. For a public release: `git push github main --tags` and
   `gh release create vX.Y.Z --title vX.Y.Z --notes "..."`

Release notes live in two places and neither is a file in this repository: this changelog holds the
history, and each GitHub release holds its published notes. `RELEASE-NOTES-*.md` is ignored so it
cannot creep back in.

## 0.0.1 (2026-09-27)

**Yeufonic 0.0.1: YuE2 Studio, renamed.** It carries on from YuE2 Studio 0.0.37, whose history and
changelog are in the archived repository, [dynamohum/YuE2gen-studio](https://github.com/dynamohum/YuE2gen-studio).
Everything YuE2 Studio did, Yeufonic does. The version numbers start again.

### Changed

- **The name.** The app, its Docker project, containers and images, the Windows installer and its
  install folder are now Yeufonic. "YuE2" still names the model the app runs.
- **On Windows, the page opens as soon as the app is up,** rather than after the engine. The engine
  starts alongside it, the header says *Engine starting…*, and anything asked for meanwhile waits.
  How long each took to start is kept in `logs\launcher.log`.
- **On Windows, Yeufonic runs like an app,** with no console window. It opens in a window of its
  own, in your default browser when that is Chrome, Edge, Brave or Vivaldi and otherwise in Edge,
  has an icon by the clock to reopen it or quit, and shows as *Yeufonic* in Task Manager.
  Closing the window leaves it running, and Quit asks first. *Yeufonic (with console)* in the
  Start menu keeps the old console for diagnosing.

### Added

- **Moving from YuE2 Studio:**
  - **Windows:** the installer finds a YuE2 Studio installation and updates it where it is, in
    its own folder. Your library, settings, LoRAs and models stay, so nothing is downloaded again.
  - **Docker:** a script moves them from an old clone into a new one.
- A saved take is tagged with its title, its lyrics and "Made with Yeufonic".
- Clicking a take's *Normalised* label undoes the normalise.
- **Normalise to** in Settings: how loud a normalised take is made, −16, −14 or −11 LUFS.

### Fixed

- Normalising a take whose peaks were already high could make its volume dip and swell. It now
  applies one gain to the whole take, and limits only the peaks that would clip.

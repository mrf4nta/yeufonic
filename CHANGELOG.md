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

## Unreleased

**Yeufonic 0.0.1: YuE2 Studio, renamed.** It carries on from YuE2 Studio 0.0.37, whose history and
changelog are in the archived repository, [dynamohum/YuE2gen-studio](https://github.com/dynamohum/YuE2gen-studio).
Everything YuE2 Studio did, Yeufonic does. The version numbers start again.

### Changed

- **The name.** The app, its Docker project, containers and images, the Windows installer and its
  install folder are now Yeufonic. "YuE2" still names the model the app runs.

### Added

- **Moving from YuE2 Studio:**
  - **Windows:** the installer finds a YuE2 Studio installation and moves it into Yeufonic's
    folder. Your library, settings, LoRAs and models come too, so nothing is downloaded again.
  - **Docker:** a script moves them from an old clone into a new one.

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

### Changed

- **Progress in the editor.** Transcribing a recording shows its progress under the recording's
  buttons, writing a score plan shows it on the Score page, and a take opened while it renders
  shows its render in the editor's bottom bar, as the job card behind the editor does. Each says
  when the job is queued behind another.

### Fixed

- A render that doesn't stop at the end of its score plays on to the length cap, and was cut off
  there mid-flow. A take stopped by its cap is now faded out over its last few seconds, and with a
  recording the cap allows about ten seconds past the score rather than thirty, so an overrun is
  short. Fixes #24.

## 0.0.6 (2026-09-28)

### Added

- **An instrumental from a recording.** Instrumental mode can take a recording, as a cover does,
  and render its transcription with the instrumental LoRA, with no plan to write. The structure is
  the score's own sections, so the whole score is played. A sung melody is given to an
  instrument wherever none plays, since a vocal part with notes makes the render sing, and an
  emptied one leaves gaps the model fills with humming. #21.
- **Ten more instrumental styles** under the Style box: acoustic pop, piano ballad, rock band,
  worship ballad, country, funk, blues, reggae, dance and orchestral, beside the first five.
- **Vocals and instruments.** Two more stem models, fast and fine tuned, split a take or a recording
  into the vocal and one **instruments** stem holding everything else, a backing track. Untick
  vocals to keep only the instruments. #20.
- **A corpus song's own style.** Picking a corpus song as the recording fills the Style box with
  the style it was learned with, as its chip has it, with the chosen LoRA's trigger word in front.
  Choosing a LoRA afterwards leaves a style typed by hand alone.

### Changed

- **The log window follows the theme,** the one in the app and the one popped out, where it
  stayed dark whatever the rest of the app wore, and in a light theme its buttons turned white on
  white.
- **The engine's own ComfyUI page is documented,** in the README and the guide: where it is, and
  that its jobs share the app's engine and GPU. Fixes #8.
- **The length cap follows a recording's score.** Choosing a recording, for a cover or an
  instrumental, sets the cap to its score's length with half a minute to spare, where 360 seconds
  would cut a longer song short. A cap typed by hand, or a take's own, is left alone.

### Fixed

- A training checkpoint, or a previous run's LoRA, showed none of its LoRA's learned styles. It now
  offers the same chips, and its **Download** carries them in the note. Fixes #17.
- A score in 6/8 was said to describe about twice the music its recording held, with a warning that
  its tempo was probably wrong when it was right. A score's length now counts each bar in quarter
  notes, a multi-bar rest as all its bars, and a change of meter part way. The same miscount could
  mark a corpus song *score: first N min* when the whole song was there. Fixes #18.
- Choosing a second recording left the first one's words in the Lyrics box, so a cover could be sung
  with another song's words. Words the app put in from a recording now follow the recording chosen,
  and go when it has none; words typed or edited in the box are replaced only after asking. Fixes #19.
- The vocal check on an instrumental listened to only three short spans, at a quarter, a half
  and three quarters, and missed a voice that came and went between them. It now hears a span from
  every fifteen seconds, so a voice lasting that long cannot fall between two. Fixes #22.
- Deleting a corpus could fail to mention its LoRA, found by a name search that missed a
  two-word name such as "First Second" in first_second_lora. It now uses the LoRA the corpus
  recorded, with its checkpoints and previous runs. Fixes #3.
- Renaming a normalised take moved its louder copy to a folder named after the new title and left
  the file as rendered in the old one, so Normalise could not be undone; the old folder stayed
  too. A rename now brings the file as rendered along and clears the old folder, and at start the
  app puts back any file as rendered an earlier rename left behind. Fixes #2.

## 0.0.5 (2026-09-28)

### Added

- **Themes.** Settings → Theme: Dark, as before; Light; Match the computer, following the
  system's light or dark; Studio, a warm dark with amber; and High contrast. It changes at once,
  and the browser remembers it so a page opens in it without a flash of the dark one. The log
  window stays dark in every theme.

### Fixed

- **+ Song** or **+ Instrumental** after a cover asked whether to discard score changes nobody had
  made. Fixes #16.
- **+ Song**, **+ Cover** and **+ Instrumental** kept the last take's style and settings. They now
  start from the defaults: an empty style (with a chosen LoRA's trigger word), a 360-second cap,
  Harmony Familiar, Plan variety normal, Interpretation Standard, Production polish on,
  Normalise off, and a new seed that is not held. A chosen LoRA stays chosen.

## 0.0.4 (2026-09-28)

### Added

- **Cover a song from a corpus.** The recording list offers every analysed corpus song, folded by
  corpus, with a filter. Picking one makes it a recording at once, with the score and words its
  analysis found, laid under the score's sections, and its separated vocal kept for Extract
  lyrics. The file is linked, not copied, where the disk allows. #14.
- **Filter a big LoRA's learned styles.** Past a dozen songs, a filter box and a row of the tags
  that recur across the corpus narrow the style chips, tags combining; the list shows its first
  dozen until Show all.
- **Finish a training run that ended early** from what it saved. The corpus window says when and
  why a run ended, and after which step; **Finish with what it saved** makes the trainer's best
  copy, or its last checkpoint, the LoRA, as a finished run does, with its checkpoints under it
  and no GPU time.
- **Run all** in the corpus window analyses, exports and trains one after the other, on the server,
  so a big corpus needs no one to wait for each step. It asks about an earlier LoRA first, analyses
  only what still needs it, leaves out and names any song whose analysis fails, and waits for
  anything already using the engine before it trains. #15.

### Fixed

- **Training no longer has a time limit.** A run was stopped at 2.5 hours, by a clock that did not
  look at progress, at step 1325 of 1400 while it was reporting a step every few seconds. The
  app told the engine to stop it. Training shows its progress and has Stop, and an engine that
  goes away, loses the job or dies is caught without a clock.
- The corpora badge could freeze on its last count, still pulsing, after one failed update during
  a restart. It now tries again.
- The New corpus window's folder picker had no way back from one of its starting folders to the
  list of them, and on Windows listed each subfolder by its whole path. It now has *all folders*
  there, and shows subfolders by name. Fixes #13.

## 0.0.3 (2026-09-27)

### Changed

- **A training run's checkpoints fold under their LoRA** in the Style LoRA list, behind a
  "▸ 9 steps" toggle beside its name, in step order, instead of sharing one Training checkpoints
  group with every other run's. A previous run's fold under its dated LoRA the same way. A
  checkpoint whose LoRA has been deleted stays in that group.

### Added

- **Same tune, new words.** The planner reads all the lyrics before it writes a note, so changed
  words get a new tune even with the same seed. When a take's words are changed in the editor,
  **Keep this tune** appears, ticked, and the main button sings the take's score with them instead:
  a new take with the same seed and whatever else the editor shows, leaving the original as it
  was. Untick it to write a new plan for the words. Before, rendering a take's score sang its saved
  words, whatever the editor held.
- **Delete a corpus's checkpoints from its Edit form.** **Training checkpoints** there lists each
  run's, this run's and any previous run's, with their sizes, to tick and delete in one go. Only
  step files: the finished LoRA keeps its own Delete LoRA, and a corpus that is training keeps its
  checkpoints until it finishes.

### Fixed

- Running out of GPU memory now says so. A job the engine failed that way said only the engine's
  CUDA error, and one lost when the engine crashed and restarted said "the engine lost the job".
  Both now say the GPU ran out of memory, with what to try, and a job lost to a restart for
  another reason says the engine stopped during it. The engine notes the error that kills its job
  thread for the app before it goes, and the app also keeps the error the engine sends for each
  job, so this does not rely on reading the engine's log, which is kept only as a fallback for an
  engine built before this. Rebuild the engine to get it. When the engine stays up without its
  job thread, still listing the dead job as running, the job fails at once instead of waiting out
  its time limit, the header says **Engine needs a restart**, and new jobs wait for the restart
  instead of queueing behind the dead one. The Train window warns before a run when less GPU
  memory is free than training needs. Fixes #12.
- The engine's start-up message, "To see the GUI go to", gave the engine's own address, and on
  Docker as 0.0.0.0, which a browser cannot open. It now gives the app's. On Docker the app's port
  can be moved with `APP_PORT` in `.env`, and the message follows it. Rebuild the engine to get
  it.
- On Docker, the app ran as user and group 1000 whatever the host's ids were, so on a host where
  yours differ its files belonged to a group, and perhaps a user, that does not exist there.
  `compose.yml` now reads `APP_UID` and `APP_GID` from `.env`, and `scripts/fetch-models.sh`
  writes yours there. An existing install can run the script again, or set them by hand; the
  README says how, and how to hand over the files written before. Fixes #11.
- Rendering a take's score again now uses the editor's style, style LoRA and strengths, length cap
  and mode. It kept the take's own, so choosing another LoRA and rendering changed nothing. With
  **keep this seed** unticked it now rolls a new seed, as the guide says, instead of reusing the
  take's.

## 0.0.2 (2026-09-27)

### Changed

- **The left panel is now a read-only sheet for the selected take,** and making and changing takes
  happens in an **editor window**: three columns with the score on a tab of its own, or steps, as
  **Settings → Editor layout** chooses. The panel's **+ Song**, **+ Cover** and **+ Instrumental**
  start something new; a card's Score and Again buttons, or a double-click on a card, open the
  editor. The panel folds away, from a chevron beside it, to give the takes the width.

### Fixed

- Opening a take in the editor now brings back its length cap, which kept whatever the last take
  had. The take panel shows the cap too.

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

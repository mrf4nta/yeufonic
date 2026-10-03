# Changelog

Versions are git tags on `main`. The number lives in `VERSION`, which is copied into the
app image and shown in the header, so a running container can be identified at a glance.

**`VERSION` moves for a change worth a number: a capability, or a change to how the app works.
A fix, a layout change or a colour does not move it; only a release gets a tag.** The number in the
header says which build is running, so it is worth keeping meaningful rather than counting deploys.
A tag, an entry here and a push are for a milestone worth naming, and are cut only when asked for —
not for every update.

To deploy a change:

1. Merge to `main` and redeploy. Bump `VERSION` only when the change is one of the above: a
   deploy that does not move it may leave a browser holding the old scripts, so hard-refresh to
   check one.

To cut a release:

0. **If the installer or the updater changed, try the update before tagging.** A test build of the
   installer can be pointed at a manifest of its own, so an update runs end to end with no tag and no
   GitHub release: see "Trying an update before it is released" in [CONTRIBUTING.md](CONTRIBUTING.md).
1. Add an entry here, newest first.
2. `git tag -a vX.Y.Z -m "..."`
3. `git push origin main --tags`   (homer only, unless GitHub is wanted)
4. For a public release: `git push github main --tags` and
   `gh release create vX.Y.Z --title vX.Y.Z --notes "..."`
5. **Announce it.** In the website repository, `python3 scripts/updates.py 0.0.13 <the
   installer>` writes `public/updates.json` — the version, the release's page, and the installer's
   URL, SHA-256 and size, computed from the file rather than copied by hand. Commit and push:
   Cloudflare deploys in about a minute. Every app asks it every four hours, so within that they
   show a newer version in the header, with the installer or the two commands to update. The script
   refuses an older version than the one on file or an installer whose name disagrees, and
   `--verify` downloads the published asset to check it is the one that was hashed.

Release notes live in two places and neither is a file in this repository: this changelog holds the
history, and each GitHub release holds its published notes. `RELEASE-NOTES-*.md` is ignored so it
cannot creep back in.

## Unreleased

### Added
- **A smaller YuE2 model for graphics cards with little memory.** The Windows installer offers
  two sizes on its components page, full quality (BF16, recommended) or low memory (INT8, 4.0 GB),
  and the Docker script takes `--int8`. An install has one: running the installer again changes it,
  and `YUE2_CHECKPOINT` forces one. The app uses whichever is installed, **About** says which, and
  LoRA training stays on the full-quality model. The README has a section on choosing between them.
  Fixes #31.

## 0.0.24 (2026-10-03)

### Fixed
- **Updating from inside the app on Windows.** The installer was started inside the app's own
  process group, so closing Yeufonic, which it needs, ended the installer with it. It is now
  started outside it, and it checks first whether Yeufonic is running: if so it asks you to close
  it and waits (Retry, or Cancel to leave everything as it is), instead of carrying on or
  stopping it for you. A silent install is unchanged.

## 0.0.23 (2026-10-03)

### Added
- **Advanced take settings.** An *Advanced* button in the song editor opens a panel of per-take
  settings: diffusion steps, an *Avoid* hint, key lock, tempo lock, the planner's score length,
  the chord hold limit and outside-chord bonus, the loudness target and the fade-out. They are
  saved with the take, the button lights up when any differs from its default, and *Reset to
  defaults* puts them all back.
- **Key lock moves the plan.** The planner does not follow a key named in the style, so the
  finished plan is moved to the key asked for: every note and chord symbol shifts by the same
  interval and the key signature is rewritten. The plan keeps its mode (a minor plan stays minor,
  with only the tonic moving). A plan it cannot read with certainty (a modal key, or a key change
  part way) is left in the planner's own key, and the log says so.

### Changed
- **MIDI imports find the real bar line.** Some MIDI files start with the first word on the beat
  before the downbeat, which put every bar marker, chord change and phrase a beat out. The drums
  and bass now decide where the first bar line is, and a lead-in gets a short bar of its own. A
  file whose rhythm section does not say is left as it was. `bar_offset` on retrack overrides it.
- **Pasted lyrics are fitted to the whole melody.** The words were shared out section by section
  by count, so one misplaced line shifted every later one, and a text longer than the melody
  squeezed everything early. They are now placed a syllable to a note over the whole song, with
  line ends pulled towards the melody's rests, line starts towards phrase starts, and the notes
  left over held after the word they belong to. Lines that cannot fit are left out from the end.

- **Studio Audio in the piano roll is a mode.** Its button stays lit while it is on, and the
  roll's Play, Pause, Rewind and bar-step controls act on the studio audio, with the cursor
  following it. Only one thing plays at a time: the roll, the notation preview and the main
  player give way to each other, and Roll Sound is greyed out while the studio audio is on.
  Pressed again, the button returns to the ordinary preview. The duplicate button beside Match
  Lyrics is gone.

### Fixed
- **MIDI Tracks window in light themes.** The track rows kept a dark background with dark text.
- **Tempo lock now sets the plan's tempo.** A style that named two tempos, or a planner that wrote
  its own, could leave the plan at a different tempo from the one asked for. The tempo lock now
  replaces the tempo in the style and in the stored plan, and the plan that is shown is the one
  that renders.
- **Tempo and key locks apply to covers.** A cover from a MIDI file or a recording's score kept
  the source's tempo in the score you read, and ignored a key lock. Both now apply to the stored
  score as well as the render.
- **Reset to defaults reaches the server.** After a reset, a plan, render or new-words request
  now puts every setting back to its default instead of keeping the take's earlier values; a
  request that says nothing about a setting still keeps the take's.

### Notes
- *Avoid* is added to the style as a hint; the renderer runs without negative conditioning, so it
  is not a guarantee.

## 0.0.22 (2026-10-03)

### Removed

- **Removed "What is new" menu item.** Removed the menu item to keep the brand menu focused and prevent external browser windows from opening behind full-screen app windows.

## 0.0.21 (2026-10-03)

### Added

- **In-app update download with live progress.** The Windows update flow now streams the installer directly into the user's Downloads folder within the app, displaying real-time download progress, byte counters, and checksum verification. This completely avoids background browser windows opening behind maximized app windows or being intercepted by browser SmartScreen prompts.
- **Direct installer launch and folder reveal.** Once downloaded and verified, the update modal offers direct "Run installer" and "Show in folder" actions.

## 0.0.20 (2026-10-03)

### Added

- **Canned styles dropdown.** A searchable dropdown directly under the Style box with 100 curated styles alphabetized for quick selection, prepending active LoRA triggers automatically.
- **Editor transport for active takes.** The transport controls now display in the editor for playable takes so songs can be auditioned directly.

### Changed & Fixed

- **Cleaner status bar.** Unified status reporting in the bottom status bar and eliminated transient status boxes across views.
- **Empty style default on new take.** Creating a new song, cover, or instrumental starts with a clean, empty style box.

## 0.0.19 (2026-10-02)

### Fixed

- **Windows installer update reliability.** Fixed an issue where updating an existing installation from within the application window was terminated prematurely by Windows Job Object cleanup when closing the previous version. You will be instructed to close any open Yeufonic window prior to running the updater.

## 0.0.18 (2026-10-02)

### Added

- **MIDI import and audition (Experimental).** Drop Standard MIDI files (`.mid`, `.midi`) into Cover mode to generate different, often off-the-wall takes of original tunes. Auto-transcription separates lead vocal melody, accompaniment, and chord progressions into ABC notation and the interactive Piano Roll.
- **Embedded MIDI lyrics extraction & phrase alignment.** Lyrics and text events inside MIDI files are extracted and aligned to the vocal melody across breath pauses and rests.
- **Large piano roll to edit MIDI notes and see how your lyrics match the vocal melody.**
- **Automatic vocal octave normalization.** MIDI lead melody tracks sequenced in lower registers (such as synth leads or guitar tracks) are automatically transposed to a natural singing register.
- **High-fidelity SoundFont audition.** MIDI files can be auditioned in-browser using FluidSynth and General MIDI SoundFonts (`.sf2`). Audio rendering includes automatic peak volume detection and normalisation with true-peak limiting, ensuring multi-track MIDI recordings audition loudly and clearly without clipping.
- **Default SoundFonts installation.** Setup scripts on both Linux/Docker (`scripts/fetch-models.sh`) and Windows (`windows/setup.ps1`) automatically download `Arachno_SoundFont_Version_1.0.sf2` and `github_Jnsgm2.sf2` into `data/models/soundfonts/sf2/`. Active SoundFont can be selected in Settings.
- **FluidSynth on Windows.** The Windows setup and launcher now automatically download and configure official FluidSynth binaries in `tools/fluidsynth/bin`.
- **Themed confirmation and input dialogs.** Destructive actions (deleting takes, stems, recordings, corpora, LoRAs, spaces, or checkpoints, and discarding unsaved score changes) use an in-app modal styled to match the application theme, with focus initially on Cancel for safety, replacing browser popups. Creating and renaming spaces and takes use in-app text prompts with Enter submission, Escape dismissal, and focus trapping.

### Changed

- **Prompt token sanitization.** Section structure markers and prompts sent to YuE2 are cleaned of embedded `w:` lyric headers, ensuring the causal language model does not suffer token collisions or skip subsequent verses.
- **The external model's words win.** With an external LLM set to hear a recording's lyrics, a reply that looks like lyrics is now always used, even where it differs a good deal from what Whisper heard, which had been refused when it had fewer than 60% of Whisper's words or when under 30% of its words matched. Whisper can miss a vocal buried in a mix, and a held syllable it loops on inflated its word count. A reply that refuses, cuts lines short, writes a notice, or is almost nothing, or an error, still falls back to Whisper. When the words cannot be matched to Whisper's times, the lines are spread over the song instead. Obviously this only really works when the lyrics are on the public Internet and can be found via LLM searches.
- **Both versions of a corpus song's words are kept,** and its Review panel has a **Words from** switch to put either in use, the external model's by default. Songs analysed before this have Whisper's or the model's lines only; analyse again to get both.
- Whisper's lines no longer hold a word repeated more than eight times in a row: a vocalise it looped on ("la" written 237 times) is cut back.

### Fixed

- **Corpora badge status scoped to the active corpus.** The top bar badge previously accumulated failed tracks across all corpora in the library, causing it to remain red and report errors in its tooltip even after switching to a corpus whose tracks had all succeeded. The badge now reflects the failure count and working state of the shown corpus.
- A plan that looped could run for ten minutes or more, mostly rests, and the render then ran to the length cap with long repeated intros and sometimes no vocal. It happened with a style LoRA, a short style and Calm plan variety together. A written plan far longer than a song (over 8 minutes, or well past a longer cap), or a song whose vocal line has no notes at all, is now written once more with a new seed, like any unreadable plan, and the take fails with advice if the second comes out the same: describe the style in more detail, or use Normal plan variety with a LoRA.

## 0.0.13 (2026-09-30)

### Added

- **The app says when a newer version is out.** Every four hours it asks its own site for the current
  release — one request, to a file on yeufonic.com, with GitHub's release as a fallback, and nothing
  else leaves the computer. A newer version shows as a quiet pill beside the version in the top bar,
  and the menu offers **Get x.y.z** — the installer on a Windows install, the two commands on the
  clipboard for a Docker copy — beside **What is new**, which opens the release notes. **Check for
  updates** asks on demand and answers in place, which is also where you can see which version you
  are running. It can be switched off in Settings; the menu works either way.
- **Hear a score plan, and take it to a DAW.** The Score window's **Notation** tab plays the plan
  with abcjs, as the box has it: **Play**, the progress, restart and a tempo control sit above the
  staves, the note being played is picked out, and clicking a note puts the cursor on the ABC it
  came from. A plan is heard as it is edited, saved or not, none of it uses the engine, and closing
  the window or moving to another tab stops it. **Download MIDI** saves the score for a DAW, the
  chord symbols written out as a part of their own — the only place the harmony is written as notes
  — and a plan that changes its metre part way is written in the metre it starts in, while the notes
  keep their own lengths.
- **A corpus being prepared says so on its own card.** The badge in the top bar has said it since
  0.0.8; the Corpora screen says it on the corpus itself now — a dot pulsing beside its name and the
  word "preparing…" — kept current while the screen is open, so a corpus working through its songs
  is not one that merely looks unfinished.
- **Every voice plays the instrument the style names.** A score names none: YuE2 writes a melody, a
  second line and chord symbols. With **Instruments** ticked the preview reads the Style the take
  was made with and plays those lines with something that fits — a guitar, a piano, strings, a
  synth, whichever the words point at — stands in for a sung line with a voice, gives the chord
  symbols a part and a bass of their own, and adds drums when the style asks for them, written
  against the score's metre: a backbeat for rock, four to the floor for dance, a ride for jazz,
  something sparser for a ballad. The line beside the player says what it chose, and unticking it
  plays a piano throughout as before. It is a reading of the style, not of the render. Each
  instrument is fetched from its upstream publisher the first time it is used — about 7 MB each,
  kept in the library, offline afterwards — and a score that runs past what its instruments can
  play is shifted by whole octaves into range, with a line saying how far.

### Changed

- **The score preview's controls stay where they can be seen.** The editor's score box takes three
  quarters of the panel it sits in rather than a share of the window, so its heading, its hint and
  the buttons under it are in view on any screen. The chevron beside it has gone: the app holds the
  block open, so it invited a click that could do nothing. The tempo reads as one control instead
  of a dark box wedged against the "%", and the notation tab's caption — "Drawn from the ABC with
  abcjs. It follows your edits." — has gone, because the view showed what it described.
- **Play says when it is preparing.** A score is played from one buffer, prepared in advance, which
  takes a moment on a long one. The line beside the player says "Getting the preview ready…" until
  the first sound, rather than the control looking like it does not work.

### Fixed

- **Changing what a preview plays no longer stops it.** Unticking Instruments or Chords mid-song
  handed the score over again — that is how abcjs changes a tune, and handing it over stops
  playback — so the place in the song is taken before the hand-over and given back after it: still
  playing, still in the same place, and a preview that was paused keeps its place.
- **The line beside the player follows the score.** It was written once from an empty box and kept
  saying "This score has no notes in it yet." while a score played.

## 0.0.8 (2026-09-29)

### Added

- **Try more.** The dice button on a take card renders the same score and words again as several
  new takes: with new seeds, or, for a take with a style LoRA that has a planner half, the same seed
  at other Planner strengths. With a LoRA the result depends on the roll as much as on the
  strengths, and this makes a set to choose from in one go. The new takes are ticked with the
  original. Fixes #27.
- **Compare.** Tick two to six takes and press Compare to play them against each other on one
  shared position: switching keeps the place in the song. Levels can be matched, the names hidden
  for a blind listen, and the one you prefer starred. Fixes #28.

### Fixed

- **Some renders clipped.** A loud render could overshoot full scale by a few dB, and saving it as
  16-bit flattened every peak past it: about one take in six had flat tops, a few of them many.
  The engine now has a peak guard between the decode and the save: it turns the audio down around
  a peak that would clip, in floating point, for a few milliseconds either side, and leaves the
  rest alone, so a render's level changes by hundredths of a dB and no sample is flat-topped. The
  app uses it when the engine has it, so rebuild the engine (`docker compose build engine`) to get
  it; an older engine keeps saving renders as before. `PEAK_GUARD=0` turns it off. Fixes #4.

### Changed

- A take's title stays on one line, ending in an ellipsis when it is long, in the wide layout as
  in the compact one; the tooltip shows the whole title. In the wide layout the details and the
  prompt each keep two lines, and the status line keeps a place of its own, so the parts of a card
  sit at the same height on every card in a row.
- The Try more button has its own icon, a die drawn in three dimensions.
- The guide's advice on LoRA strengths says how to find a good take: the Sound strength changes the
  voice little between 0.3 and 0.6, and the Planner strength works like another seed.

## 0.0.7 (2026-09-29)

### Added

- **Search the takes.** A search box beside the library's filters finds takes with every word typed
  in the title, style, lyrics or LoRA name. It looks through the space on show, or every space with
  the All spaces chip, where a card from another space names it. The last few searches that found
  something are offered under the box. Fixes #26.

### Changed

- **Training takes as much of each song as the card allows.** The cut was a fixed 3½ minutes, so
  most songs in a corpus were cut short. `TRAIN_MAX_MINUTES` and `TRAIN_MAX_TOKENS` now default
  to `auto`: when a corpus is exported and when training starts, the app reads the graphics
  card's free memory and works out how much of each song the dataset builder can hold, and a
  context to fit (about 5½ minutes on a 16 GB card, never below 3½ nor above 6, nor past the
  longest song). The Logs window says what was chosen. Setting either to a number, such as
  `3.5`, overrides it, and a training run that runs out of memory now says so.
- **Training cuts a long song at a section end.** A song longer than the training limit was cut
  where the limit fell, mid-bar, with the whole song's words, so the planner learned that songs
  stop abruptly and were sung words they never reached. The export now cuts it at the end of the
  last section within the limit, fades it out, and keeps only the words of the sections that are
  still heard; with no section end near enough it cuts at the limit as before. The corpus window
  says how much of each long song is trained. Fixes #7.
- **Progress in the editor.** Transcribing a recording shows its progress under the recording's
  buttons, writing a score plan shows it on the Score page, and a take opened while it renders
  shows its render in the editor's bottom bar, as the job card behind the editor does. Each says
  when the job is queued behind another.

### Fixed

- The plan check let through plans that read as scores but couldn't be sung: a vocal line
  spanning more than three octaves, the metre changing more than four times, or a dozen chords
  with double sharps or flats. These are now caught, and, like any unreadable plan, written once
  more with a new seed before the take is marked failed. Fixes #5.
- A render that doesn't stop at the end of its score plays on to the length cap, and was cut off
  there mid-flow. A take stopped by its cap is now faded out over its last few seconds, and with a
  recording the cap allows about ten seconds past the score rather than thirty, so an overrun is
  short. Fixes #24.
- Now and then a render ended long before its score, and the take looked like a short song. A
  render that ends before 60% of its score is now tried once more with a new seed before it's
  called finished; if that ends early too, it's kept, and its card says it stopped early. Fixes #25.

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

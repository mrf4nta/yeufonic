/**
 * Visual Piano Roll / MIDI Editor for Yeufonic
 * Bidirectional ABC notation <-> visual interactive note editing.
 */
(function (global) {
  'use strict';

  var MIN_PITCH = 24; // C1
  var MAX_PITCH = 96; // C7
  var NUM_PITCHES = MAX_PITCH - MIN_PITCH + 1; // 73 pitches
  var ROW_HEIGHT = 20; // px per semitone
  var TICK_WIDTH = 18; // px per tick (16th note default)

  var PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  var BLACK_KEYS = [false, true, false, true, false, false, true, false, true, false, true, false];

  var KEY_ACCIDENTALS = {
    'C': { flats: false }, 'G': { flats: false }, 'D': { flats: false }, 'A': { flats: false },
    'E': { flats: false }, 'B': { flats: false }, 'F#': { flats: false },
    'F': { flats: true }, 'Bb': { flats: true }, 'Eb': { flats: true },
    'Ab': { flats: true }, 'Db': { flats: true }, 'Gb': { flats: true },
    'Am': { flats: false }, 'Em': { flats: false }, 'Bm': { flats: false }, 'F#m': { flats: false },
    'Dm': { flats: true }, 'Gm': { flats: true }, 'Cm': { flats: true }, 'Fm': { flats: true }
  };

  var SHARP_NAMES = ["C", "^C", "D", "^D", "E", "F", "^F", "G", "^G", "A", "^A", "B"];
  var FLAT_NAMES  = ["C", "_D", "D", "_E", "E", "F", "_G", "G", "_A", "A", "_B", "B"];

  function midiToNoteName(pitch) {
    var semitone = ((pitch % 12) + 12) % 12;
    var octave = Math.floor(pitch / 12) - 1;
    return PITCH_NAMES[semitone] + octave;
  }

  function midiToAbcNote(pitch, key) {
    var isFlat = key && KEY_ACCIDENTALS[key] && KEY_ACCIDENTALS[key].flats;
    var names = isFlat ? FLAT_NAMES : SHARP_NAMES;
    var oct = Math.floor(pitch / 12) - 1;
    var semitone = ((pitch % 12) + 12) % 12;
    var rawName = names[semitone];
    
    var acc = "";
    var letter = rawName;
    if (rawName.charAt(0) === '^' || rawName.charAt(0) === '_') {
      acc = rawName.charAt(0);
      letter = rawName.slice(1);
    }

    var noteBody = "";
    if (oct < 4) {
      noteBody = letter;
      for (var i = 0; i < 4 - oct; i++) { noteBody += ","; }
    } else if (oct === 4) {
      noteBody = letter;
    } else if (oct === 5) {
      noteBody = letter.toLowerCase();
    } else {
      noteBody = letter.toLowerCase();
      for (var j = 0; j < oct - 5; j++) { noteBody += "'"; }
    }
    return acc + noteBody;
  }

  function abcNoteToMidi(accidental, letter, octaves) {
    var baseMap = { C: 60, D: 62, E: 64, F: 65, G: 67, A: 69, B: 71 };
    var isLower = letter === letter.toLowerCase();
    var base = baseMap[letter.toUpperCase()];
    if (base === undefined) { base = 60; }
    if (isLower) { base += 12; }
    if (octaves) {
      for (var i = 0; i < octaves.length; i++) {
        var ch = octaves.charAt(i);
        if (ch === "'") { base += 12; }
        if (ch === ",") { base -= 12; }
      }
    }
    if (accidental) {
      for (var j = 0; j < accidental.length; j++) {
        var a = accidental.charAt(j);
        if (a === '^') { base += 1; }
        if (a === '_') { base -= 1; }
      }
    }
    return base;
  }

  /* ---------------------------------------------------- Web Audio Synth */
  var audioCtx = null;
  function getAudioContext() {
    if (!audioCtx) {
      var AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume().catch(function () {});
    }
    return audioCtx;
  }

  var activeOscillators = [];

  function stopAllAudio() {
    for (var i = 0; i < activeOscillators.length; i++) {
      try {
        activeOscillators[i].stop();
        activeOscillators[i].disconnect();
      } catch (err) {}
    }
    activeOscillators = [];
  }

  function midiToFreq(pitch) {
    return 440 * Math.pow(2, (pitch - 69) / 12);
  }

  function playTone(pitch, durationSec, voiceType, startTime) {
    var ctx = getAudioContext();
    if (!ctx) { return null; }
    var now = startTime !== undefined ? startTime : ctx.currentTime;
    var dur = durationSec || 0.25;
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    var filter = ctx.createBiquadFilter();

    osc.type = voiceType === 'Ins' ? 'sawtooth' : 'triangle';
    osc.frequency.setValueAtTime(midiToFreq(pitch), now);

    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(voiceType === 'Ins' ? 1400 : 2400, now);

    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.25, now + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.15, now + Math.min(0.08, dur * 0.5));
    gain.gain.exponentialRampToValueAtTime(0.0001, now + dur);

    osc.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + dur + 0.04);

    activeOscillators.push(osc);
    osc.onended = function () {
      var idx = activeOscillators.indexOf(osc);
      if (idx !== -1) { activeOscillators.splice(idx, 1); }
    };
    return osc;
  }

  /* ---------------------------------------------------- ABC Parser */
  function parseAbc(abcText) {
    var lines = (abcText || "").split(/\r?\n/);
    var headers = [];
    var sections = [];
    var voices = [];
    var chords = [];
    var rawNotes = [];
    
    var key = "C";
    var currentVoice = "Vocal";
    var voiceBarIndex = {};
    var ticksPerBar = 16;
    var unitLength = 16;
    var bpm = 120;

    var tokenRe = /"([^"]*)"|([zZ])(\d*)|([_^=]*[A-Ga-g][,']*)(\d*)(-?)|(\|)/g;
    var nextId = 1;

    for (var lineIndex = 0; lineIndex < lines.length; lineIndex++) {
      var raw = lines[lineIndex].trim();
      if (!raw) { continue; }

      if (raw.charAt(0) === "%") {
        var currentBar = voiceBarIndex[currentVoice] || 0;
        sections.push({ barIndex: currentBar, text: raw });
        continue;
      }

      if (raw.indexOf("V:") === 0) {
        var vMatch = raw.match(/^V:\s*(\S+)/);
        if (vMatch) {
          currentVoice = vMatch[1];
          if (voices.indexOf(currentVoice) === -1) { voices.push(currentVoice); }
          if (voiceBarIndex[currentVoice] === undefined) { voiceBarIndex[currentVoice] = 0; }
        }
        continue;
      }

      if (/^[A-Za-z]:/.test(raw) && raw.indexOf("V:") !== 0) {
        headers.push(raw);
        if (raw.indexOf("K:") === 0) {
          var km = raw.match(/^K:\s*([A-Ga-g][#b]?[m]?)/);
          if (km) { key = km[1]; }
        }
        if (raw.indexOf("Q:") === 0) {
          var qm = raw.match(/^Q:1\/4=(\d+)/);
          if (qm) { bpm = parseInt(qm[1], 10); }
        }
        if (raw.indexOf("L:") === 0) {
          var lm = raw.match(/^L:\s*1\/(\d+)/);
          if (lm) { unitLength = parseInt(lm[1], 10); }
        }
        if (raw.indexOf("M:") === 0) {
          var mm = raw.match(/^M:\s*(\d+)\/(\d+)/);
          if (mm) {
            var num = parseInt(mm[1], 10);
            var den = parseInt(mm[2], 10);
            ticksPerBar = Math.round(num * (unitLength / den));
          }
        }
        continue;
      }

      if (voiceBarIndex[currentVoice] === undefined) { voiceBarIndex[currentVoice] = 0; }
      var tickInBar = 0;

      var match;
      tokenRe.lastIndex = 0;
      while ((match = tokenRe.exec(raw)) !== null) {
        if (match[1]) {
          chords.push({
            voice: currentVoice,
            barIndex: voiceBarIndex[currentVoice],
            tickInBar: tickInBar,
            name: match[1]
          });
        } else if (match[2]) {
          var restType = match[2];
          if (restType === "Z") {
            var count = parseInt(match[3] || "1", 10);
            voiceBarIndex[currentVoice] += count;
            tickInBar = 0;
          } else {
            var rDur = parseInt(match[3] || "1", 10);
            tickInBar += rDur;
          }
        } else if (match[4]) {
          var noteStr = match[4];
          var nDur = parseInt(match[5] || "1", 10);
          var tiedNext = match[6] === "-";
          
          var noteParts = noteStr.match(/^([_^=]*)([A-Ga-g])([,']*)$/);
          if (noteParts) {
            var pitch = abcNoteToMidi(noteParts[1], noteParts[2], noteParts[3]);
            rawNotes.push({
              id: nextId++,
              voice: currentVoice,
              pitch: pitch,
              barIndex: voiceBarIndex[currentVoice],
              tickInBar: tickInBar,
              durationTicks: nDur,
              tiedNext: tiedNext
            });
          }
          tickInBar += nDur;
        } else if (match[7]) {
          voiceBarIndex[currentVoice] += 1;
          tickInBar = 0;
        }
      }
    }

    rawNotes.sort(function (a, b) {
      if (a.voice !== b.voice) { return a.voice.localeCompare(b.voice); }
      if (a.barIndex !== b.barIndex) { return a.barIndex - b.barIndex; }
      return a.tickInBar - b.tickInBar;
    });

    var notes = [];
    for (var i = 0; i < rawNotes.length; i++) {
      var rn = rawNotes[i];
      var absTick = rn.barIndex * ticksPerBar + rn.tickInBar;
      
      if (notes.length > 0) {
        var prev = notes[notes.length - 1];
        if (prev.voice === rn.voice && prev.pitch === rn.pitch && prev._tiedNext && (prev.startTick + prev.durationTicks === absTick)) {
          prev.durationTicks += rn.durationTicks;
          prev._tiedNext = rn.tiedNext;
          continue;
        }
      }

      notes.push({
        id: rn.id,
        voice: rn.voice,
        pitch: rn.pitch,
        startTick: absTick,
        durationTicks: rn.durationTicks,
        _tiedNext: rn.tiedNext
      });
    }

    for (var k = 0; k < notes.length; k++) {
      delete notes[k]._tiedNext;
    }

    if (voices.indexOf("Vocal") === -1) { voices.push("Vocal"); }
    if (voices.indexOf("Ins") === -1) { voices.push("Ins"); }

    return {
      headers: headers,
      key: key,
      bpm: bpm,
      ticksPerBar: ticksPerBar,
      unitLength: unitLength,
      voices: voices,
      sections: sections,
      chords: chords,
      notes: notes
    };
  }

  /* ---------------------------------------------------- ABC Serializer */
  function serializeToAbc(model) {
    var lines = [];
    var ticksPerBar = model.ticksPerBar || 16;
    var key = model.key || "C";

    for (var h = 0; h < model.headers.length; h++) {
      lines.push(model.headers[h]);
    }

    if (!model.headers.some(function (x) { return /^V:\s*Vocal\b/.test(x); })) {
      lines.push('V: Vocal clef=treble name="Vocal Melody" snm="Vocal"');
    }
    if (!model.headers.some(function (x) { return /^V:\s*Ins\b/.test(x); })) {
      lines.push('V: Ins clef=treble name="Ins Melody" snm="Inst."');
    }
    if (!model.headers.some(function (x) { return /^K:/.test(x); })) {
      lines.push('K:' + key);
    }

    var maxBar = 3;
    for (var n = 0; n < model.notes.length; n++) {
      var note = model.notes[n];
      var endBar = Math.floor((note.startTick + note.durationTicks - 1) / ticksPerBar);
      if (endBar > maxBar) { maxBar = endBar; }
    }
    for (var c = 0; c < model.chords.length; c++) {
      if (model.chords[c].barIndex > maxBar) { maxBar = model.chords[c].barIndex; }
    }
    for (var s = 0; s < model.sections.length; s++) {
      if (model.sections[s].barIndex > maxBar) { maxBar = model.sections[s].barIndex; }
    }

    var barSegments = {};
    for (var vIdx = 0; vIdx < model.voices.length; vIdx++) {
      var vName = model.voices[vIdx];
      barSegments[vName] = {};
      for (var b = 0; b <= maxBar; b++) {
        barSegments[vName][b] = [];
      }
    }

    for (var m = 0; m < model.notes.length; m++) {
      var curNote = model.notes[m];
      var remDur = curNote.durationTicks;
      var curTick = curNote.startTick;

      while (remDur > 0) {
        var bIndex = Math.floor(curTick / ticksPerBar);
        var tInBar = curTick % ticksPerBar;
        var spaceInBar = ticksPerBar - tInBar;
        var segDur = Math.min(remDur, spaceInBar);
        var isTied = remDur > segDur;

        if (!barSegments[curNote.voice]) { barSegments[curNote.voice] = {}; }
        if (!barSegments[curNote.voice][bIndex]) { barSegments[curNote.voice][bIndex] = []; }

        barSegments[curNote.voice][bIndex].push({
          tickInBar: tInBar,
          durationTicks: segDur,
          pitch: curNote.pitch,
          tied: isTied
        });

        remDur -= segDur;
        curTick += segDur;
      }
    }

    var sortedSections = model.sections.slice().sort(function (a, b) { return a.barIndex - b.barIndex; });
    if (sortedSections.length === 0) {
      sortedSections.push({ barIndex: 0, text: "% intro" });
    } else if (sortedSections[0].barIndex > 0) {
      sortedSections.unshift({ barIndex: 0, text: "% intro" });
    }

    var sectionIntervals = [];
    for (var si = 0; si < sortedSections.length; si++) {
      var secItem = sortedSections[si];
      var nextStart = (si + 1 < sortedSections.length) ? sortedSections[si + 1].barIndex : (maxBar + 1);
      sectionIntervals.push({
        text: secItem.text,
        startBar: secItem.barIndex,
        endBar: Math.max(secItem.barIndex + 1, nextStart)
      });
    }

    for (var intIdx = 0; intIdx < sectionIntervals.length; intIdx++) {
      var sec = sectionIntervals[intIdx];
      lines.push(sec.text);

      for (var vi = 0; vi < model.voices.length; vi++) {
        var voiceName = model.voices[vi];
        lines.push('V: ' + voiceName);
        var barBuffer = [];

        for (var barNum = sec.startBar; barNum < sec.endBar && barNum <= maxBar; barNum++) {
          var segs = (barSegments[voiceName] && barSegments[voiceName][barNum]) ? barSegments[voiceName][barNum] : [];
          segs.sort(function (a, b) { return a.tickInBar - b.tickInBar; });

          var barChords = model.chords.filter(function (ch) {
            return ch.barIndex === barNum && (ch.voice === voiceName || (!ch.voice && voiceName === "Vocal"));
          });
          var chordMap = {};
          for (var ci = 0; ci < barChords.length; ci++) {
            chordMap[barChords[ci].tickInBar] = barChords[ci].name;
          }

          var curBarTick = 0;
          var barStr = "";

          if (segs.length === 0) {
            if (chordMap[0]) { barStr += '"' + chordMap[0] + '"'; }
            barStr += 'z' + ticksPerBar;
          } else {
            for (var segIdx = 0; segIdx < segs.length; segIdx++) {
              var s = segs[segIdx];
              if (s.tickInBar > curBarTick) {
                var rDur = s.tickInBar - curBarTick;
                if (chordMap[curBarTick]) { barStr += '"' + chordMap[curBarTick] + '"'; }
                barStr += 'z' + (rDur > 1 ? rDur : "");
                curBarTick = s.tickInBar;
              }
              if (chordMap[curBarTick]) {
                barStr += '"' + chordMap[curBarTick] + '"';
              }
              var nStr = midiToAbcNote(s.pitch, key);
              var dStr = s.durationTicks > 1 ? String(s.durationTicks) : "";
              var tStr = s.tied ? "-" : "";
              barStr += nStr + dStr + tStr;
              curBarTick += s.durationTicks;
            }
            if (curBarTick < ticksPerBar) {
              var endRest = ticksPerBar - curBarTick;
              if (chordMap[curBarTick]) { barStr += '"' + chordMap[curBarTick] + '"'; }
              barStr += 'z' + (endRest > 1 ? endRest : "");
            }
          }

          barBuffer.push(barStr);

          if (barBuffer.length === 4 || barNum === sec.endBar - 1 || barNum === maxBar) {
            lines.push(barBuffer.join(" | ") + " |");
            barBuffer = [];
          }
        }
      }
    }

    return lines.join("\n") + "\n";
  }

  /* ---------------------------------------------------- PianoRoll Controller */
  var PianoRoll = {
    model: null,
    currentVoice: "Vocal",
    ghostOther: true,
    snapTicks: 1, // 1 = 1/16, 2 = 1/8, 4 = 1/4
    tickWidth: TICK_WIDTH,
    rowHeight: ROW_HEIGHT,
    selectedNoteId: null,
    isPlaying: false,
    playheadTick: 0,
    playTimer: null,
    playStartTime: 0,
    playStartTick: 0,
    listeners: [],
    initialized: false,

    init: function () {
      if (this.initialized) { return; }
      this.initialized = true;

      var self = this;

      // Voice selectors
      var vocalBtn = document.getElementById('roll-voice-vocal');
      var insBtn = document.getElementById('roll-voice-ins');
      if (vocalBtn) {
        vocalBtn.addEventListener('click', function () { self.setVoice('Vocal'); });
      }
      if (insBtn) {
        insBtn.addEventListener('click', function () { self.setVoice('Ins'); });
      }

      // Ghost checkbox
      var ghostCheck = document.getElementById('roll-ghost');
      if (ghostCheck) {
        ghostCheck.addEventListener('change', function () {
          self.ghostOther = ghostCheck.checked;
          self.renderNotes();
        });
      }

      // Snap dropdown
      var snapSel = document.getElementById('roll-snap-val');
      if (snapSel) {
        snapSel.addEventListener('change', function () {
          var val = parseInt(snapSel.value, 10);
          self.snapTicks = Math.round(16 / val);
        });
      }

      // Transport Rewind / Prev / Play / Next
      var rewindBtn = document.getElementById('roll-rewind');
      if (rewindBtn) {
        rewindBtn.addEventListener('click', function () { self.rewindToStart(); });
      }
      var prevBtn = document.getElementById('roll-prev');
      if (prevBtn) {
        prevBtn.addEventListener('click', function () { self.stepPrev(); });
      }
      var playBtn = document.getElementById('roll-play');
      if (playBtn) {
        playBtn.addEventListener('click', function () { self.togglePlay(); });
      }
      var nextBtn = document.getElementById('roll-next');
      if (nextBtn) {
        nextBtn.addEventListener('click', function () { self.stepNext(); });
      }

      // History Undo / Redo
      var undoBtn = document.getElementById('roll-undo-btn');
      if (undoBtn) {
        undoBtn.addEventListener('click', function () {
          if (global.undoScore) { global.undoScore(); }
        });
      }
      var redoBtn = document.getElementById('roll-redo-btn');
      if (redoBtn) {
        redoBtn.addEventListener('click', function () {
          if (global.redoScore) { global.redoScore(); }
        });
      }

      // Zoom controls
      var zoomIn = document.getElementById('roll-zoom-in');
      var zoomOut = document.getElementById('roll-zoom-out');
      var zoomFit = document.getElementById('roll-zoom-fit');
      if (zoomIn) {
        zoomIn.addEventListener('click', function () {
          self.tickWidth = Math.min(36, self.tickWidth + 4);
          self.renderAll();
        });
      }
      if (zoomOut) {
        zoomOut.addEventListener('click', function () {
          self.tickWidth = Math.max(8, self.tickWidth - 4);
          self.renderAll();
        });
      }
      if (zoomFit) {
        zoomFit.addEventListener('click', function () {
          self.scrollToNotes();
        });
      }

      // Show / Hide ABC text split toggle
      var toggleTextBtn = document.getElementById('roll-toggle-text');
      if (toggleTextBtn) {
        toggleTextBtn.addEventListener('click', function () {
          var modalBox = document.querySelector('.modal-box.score');
          if (modalBox) {
            modalBox.classList.toggle('show-split');
            toggleTextBtn.textContent = modalBox.classList.contains('show-split') ? 'Hide ABC' : 'Show ABC';
          }
        });
      }

      // Synchronized scrolling
      var gridScroll = document.getElementById('roll-grid-scroll');
      var keysEl = document.getElementById('roll-keys');
      var timelineHeader = document.getElementById('roll-timeline-header');
      if (gridScroll) {
        gridScroll.addEventListener('scroll', function () {
          if (keysEl) { keysEl.scrollTop = gridScroll.scrollTop; }
          if (timelineHeader) { timelineHeader.scrollLeft = gridScroll.scrollLeft; }
        });
      }

      // Grid interactions: note click, move, resize, add
      this.bindGridEvents();
    },

    setVoice: function (voiceName) {
      this.currentVoice = voiceName;
      var vocalBtn = document.getElementById('roll-voice-vocal');
      var insBtn = document.getElementById('roll-voice-ins');
      if (vocalBtn) { vocalBtn.classList.toggle('active', voiceName === 'Vocal'); }
      if (insBtn) { insBtn.classList.toggle('active', voiceName === 'Ins'); }
      this.renderNotes();
    },

    loadAbc: function (abcText) {
      this.model = parseAbc(abcText);
      this.renderAll();
      var self = this;
      setTimeout(function () { self.scrollToNotes(); }, 50);
    },

    render: function (abcText) {
      this.init();
      this.stop();
      this.loadAbc(abcText);
    },

    renderAll: function () {
      if (!this.model) { return; }
      this.updateMetadata();
      this.renderKeys();
      this.renderTimeline();
      this.renderGrid();
      this.renderNotes();
      this.updatePlayhead();
    },

    updateMetadata: function () {
      var metaEl = document.getElementById('roll-meta');
      if (metaEl && this.model) {
        metaEl.textContent = 'Key ' + this.model.key + ' • ' + (this.model.ticksPerBar === 16 ? '4/4' : 'Metre') + ' • ' + this.model.bpm + ' BPM';
      }
    },

    renderKeys: function () {
      var keysEl = document.getElementById('roll-keys');
      if (!keysEl) { return; }
      var self = this;
      var html = [];

      for (var p = MAX_PITCH; p >= MIN_PITCH; p--) {
        var semitone = ((p % 12) + 12) % 12;
        var isBlack = BLACK_KEYS[semitone];
        var name = midiToNoteName(p);
        var isC = semitone === 0;

        html.push(
          '<div class="roll-key ' + (isBlack ? 'black' : 'white') + (isC ? ' c-key' : '') + '" ' +
          'data-pitch="' + p + '" style="height:' + self.rowHeight + 'px; line-height:' + self.rowHeight + 'px">' +
          '<span class="key-label">' + (isC || isBlack ? name : '') + '</span>' +
          '</div>'
        );
      }
      keysEl.innerHTML = html.join('');

      // Key click to audition note
      var keyNodes = keysEl.querySelectorAll('.roll-key');
      Array.prototype.forEach.call(keyNodes, function (node) {
        node.addEventListener('pointerdown', function () {
          var pitch = parseInt(node.dataset.pitch, 10);
          node.classList.add('pressed');
          playTone(pitch, 0.35, self.currentVoice);
        });
        node.addEventListener('pointerup', function () { node.classList.remove('pressed'); });
        node.addEventListener('pointerleave', function () { node.classList.remove('pressed'); });
      });
    },

    renderTimeline: function () {
      var rulerEl = document.getElementById('roll-ruler');
      var chordsEl = document.getElementById('roll-chords-track');
      if (!rulerEl || !chordsEl || !this.model) { return; }

      var ticksPerBar = this.model.ticksPerBar || 16;
      var totalTicks = this.getTotalTicks();
      var totalBars = Math.ceil(totalTicks / ticksPerBar);
      var self = this;

      // Section markers
      var sectionMap = {};
      for (var s = 0; s < this.model.sections.length; s++) {
        var sec = this.model.sections[s];
        sectionMap[sec.barIndex] = sec.text.replace(/^%\s*/, '');
      }

      var rulerHtml = [];
      for (var b = 0; b < totalBars; b++) {
        var left = b * ticksPerBar * self.tickWidth;
        var width = ticksPerBar * self.tickWidth;
        var secName = sectionMap[b];

        rulerHtml.push(
          '<div class="roll-bar-marker" style="left:' + left + 'px; width:' + width + 'px">' +
          (secName ? '<span class="roll-sec-badge" data-bar="' + b + '">' + secName + '</span>' : '') +
          '<span class="roll-bar-num">' + (b + 1) + '</span>' +
          '</div>'
        );
      }
      rulerEl.style.width = (totalTicks * self.tickWidth) + 'px';
      rulerEl.innerHTML = rulerHtml.join('');

      // Click on ruler to move playhead
      rulerEl.onclick = function (e) {
        var rect = rulerEl.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var clickedTick = Math.max(0, Math.floor(x / self.tickWidth));
        self.seekTick(clickedTick);
      };

      // Click on section badge to edit section name
      var badges = rulerEl.querySelectorAll('.roll-sec-badge');
      Array.prototype.forEach.call(badges, function (badge) {
        badge.onclick = function (e) {
          e.stopPropagation();
          var barIndex = parseInt(badge.dataset.bar, 10);
          var current = badge.textContent.trim();
          var newName = window.prompt("Section name (e.g. intro, verse, chorus):", current);
          if (newName !== null) {
            newName = newName.trim();
            for (var si = 0; si < self.model.sections.length; si++) {
              if (self.model.sections[si].barIndex === barIndex) {
                self.model.sections[si].text = newName ? ("% " + newName) : "";
              }
            }
            self.model.sections = self.model.sections.filter(function (x) { return x.text; });
            self.commitEdit();
          }
        };
      });

      // Chords lane
      var chordHtml = [];
      for (var cb = 0; cb < totalBars; cb++) {
        var bLeft = cb * ticksPerBar * self.tickWidth;
        var bWidth = ticksPerBar * self.tickWidth;
        chordHtml.push(
          '<div class="roll-chord-slot" data-bar="' + cb + '" style="left:' + bLeft + 'px; width:' + bWidth + 'px"></div>'
        );
      }
      for (var ci = 0; ci < this.model.chords.length; ci++) {
        var ch = this.model.chords[ci];
        var chTick = ch.barIndex * ticksPerBar + (ch.tickInBar || 0);
        var chLeft = chTick * self.tickWidth;
        chordHtml.push(
          '<span class="roll-chord-tag" data-chord-idx="' + ci + '" style="left:' + chLeft + 'px">' +
          ch.name + '</span>'
        );
      }
      chordsEl.style.width = (totalTicks * self.tickWidth) + 'px';
      chordsEl.innerHTML = chordHtml.join('');

      // Click chord to edit, or slot to add
      chordsEl.onclick = function (e) {
        var tag = e.target.closest('.roll-chord-tag');
        if (tag) {
          var idx = parseInt(tag.dataset.chordIdx, 10);
          var chord = self.model.chords[idx];
          var newChord = window.prompt("Edit chord name (e.g. C, Dm7, G/B):", chord.name);
          if (newChord !== null) {
            newChord = newChord.trim();
            if (newChord) {
              chord.name = newChord;
            } else {
              self.model.chords.splice(idx, 1);
            }
            self.commitEdit();
          }
          return;
        }
        var slot = e.target.closest('.roll-chord-slot');
        if (slot) {
          var bar = parseInt(slot.dataset.bar, 10);
          var rectS = slot.getBoundingClientRect();
          var offsetTick = Math.floor((e.clientX - rectS.left) / self.tickWidth);
          var entered = window.prompt("Add chord for bar " + (bar + 1) + ":", "C");
          if (entered && entered.trim()) {
            self.model.chords.push({
              voice: self.currentVoice,
              barIndex: bar,
              tickInBar: offsetTick,
              name: entered.trim()
            });
            self.commitEdit();
          }
        }
      };
    },

    getTotalTicks: function () {
      if (!this.model) { return 64; }
      var ticksPerBar = this.model.ticksPerBar || 16;
      var maxTick = 16 * 4; // at least 4 bars
      for (var n = 0; n < this.model.notes.length; n++) {
        var end = this.model.notes[n].startTick + this.model.notes[n].durationTicks;
        if (end > maxTick) { maxTick = end; }
      }
      for (var c = 0; c < this.model.chords.length; c++) {
        var chEnd = (this.model.chords[c].barIndex + 1) * ticksPerBar;
        if (chEnd > maxTick) { maxTick = chEnd; }
      }
      // Round up to full bar + 2 extra empty bars for breathing room
      var bars = Math.ceil(maxTick / ticksPerBar) + 2;
      return bars * ticksPerBar;
    },

    renderGrid: function () {
      var gridEl = document.getElementById('roll-grid');
      var linesEl = document.getElementById('roll-grid-lines');
      if (!gridEl || !linesEl || !this.model) { return; }

      var totalTicks = this.getTotalTicks();
      var ticksPerBar = this.model.ticksPerBar || 16;
      var totalWidth = totalTicks * this.tickWidth;
      var totalHeight = NUM_PITCHES * this.rowHeight;
      var self = this;

      gridEl.style.width = totalWidth + 'px';
      gridEl.style.height = totalHeight + 'px';

      var linesHtml = [];
      // Horizontal row backgrounds
      for (var p = MAX_PITCH; p >= MIN_PITCH; p--) {
        var semitone = ((p % 12) + 12) % 12;
        var isBlack = BLACK_KEYS[semitone];
        var top = (MAX_PITCH - p) * self.rowHeight;
        linesHtml.push(
          '<div class="roll-row ' + (isBlack ? 'black-row' : 'white-row') + '" ' +
          'style="top:' + top + 'px; height:' + self.rowHeight + 'px"></div>'
        );
      }

      // Vertical tick / beat / bar lines
      var beatsPerBar = 4;
      var ticksPerBeat = Math.round(ticksPerBar / beatsPerBar);

      for (var t = 0; t <= totalTicks; t++) {
        var isBar = (t % ticksPerBar === 0);
        var isBeat = (t % ticksPerBeat === 0);
        var left = t * self.tickWidth;

        if (isBar || isBeat || self.tickWidth >= 16) {
          linesHtml.push(
            '<div class="roll-vline ' + (isBar ? 'bar-line' : (isBeat ? 'beat-line' : 'tick-line')) + '" ' +
            'style="left:' + left + 'px"></div>'
          );
        }
      }

      linesEl.innerHTML = linesHtml.join('');
    },

    renderNotes: function () {
      var notesLayer = document.getElementById('roll-notes-layer');
      if (!notesLayer || !this.model) { return; }
      var self = this;
      var html = [];

      for (var i = 0; i < this.model.notes.length; i++) {
        var note = this.model.notes[i];
        var isCurrentVoice = note.voice === self.currentVoice;
        if (!isCurrentVoice && !self.ghostOther) { continue; }

        var left = note.startTick * self.tickWidth;
        var top = (MAX_PITCH - note.pitch) * self.rowHeight;
        var width = Math.max(4, note.durationTicks * self.tickWidth - 2);
        var height = self.rowHeight - 2;
        var isSelected = (note.id === self.selectedNoteId);
        var noteName = midiToNoteName(note.pitch);

        var voiceClass = (note.voice === 'Ins') ? 'ins' : 'vocal';
        var ghostClass = isCurrentVoice ? '' : 'ghost';
        var selClass = isSelected ? 'selected' : '';

        html.push(
          '<div class="roll-note ' + voiceClass + ' ' + ghostClass + ' ' + selClass + '" ' +
          'data-note-id="' + note.id + '" ' +
          'style="left:' + left + 'px; top:' + top + 'px; width:' + width + 'px; height:' + height + 'px">' +
          '<span class="roll-note-title">' + (width > 22 ? noteName : '') + '</span>' +
          (isCurrentVoice ? '<div class="roll-note-resize"></div>' : '') +
          '</div>'
        );
      }

      notesLayer.innerHTML = html.join('');
    },

    bindGridEvents: function () {
      var gridEl = document.getElementById('roll-grid');
      var gridScroll = document.getElementById('roll-grid-scroll');
      if (!gridEl || !gridScroll) { return; }
      var self = this;

      var dragState = null;

      gridEl.addEventListener('pointerdown', function (e) {
        var resizeHandle = e.target.closest('.roll-note-resize');
        var noteEl = e.target.closest('.roll-note');

        if (resizeHandle) {
          // Resize note
          e.preventDefault();
          e.stopPropagation();
          var pNoteEl = resizeHandle.closest('.roll-note');
          var rId = parseInt(pNoteEl.dataset.noteId, 10);
          var rNote = self.findNote(rId);
          if (!rNote) { return; }

          self.selectedNoteId = rId;
          self.renderNotes();

          dragState = {
            type: 'resize',
            note: rNote,
            startX: e.clientX,
            origDuration: rNote.durationTicks
          };
          window.addEventListener('pointermove', onPointerMove);
          window.addEventListener('pointerup', onPointerUp);
          return;
        }

        if (noteEl) {
          // Move or select note
          if (noteEl.classList.contains('ghost')) { return; }
          e.preventDefault();
          e.stopPropagation();
          var nId = parseInt(noteEl.dataset.noteId, 10);
          var mNote = self.findNote(nId);
          if (!mNote) { return; }

          self.selectedNoteId = nId;
          self.renderNotes();
          playTone(mNote.pitch, 0.2, self.currentVoice);

          dragState = {
            type: 'move',
            note: mNote,
            startX: e.clientX,
            startY: e.clientY,
            origStartTick: mNote.startTick,
            origPitch: mNote.pitch,
            lastPitch: mNote.pitch
          };
          window.addEventListener('pointermove', onPointerMove);
          window.addEventListener('pointerup', onPointerUp);
          return;
        }

        // Click on empty grid cell -> create note
        var rect = gridEl.getBoundingClientRect();
        var clickX = e.clientX - rect.left;
        var clickY = e.clientY - rect.top;

        var clickedTick = Math.max(0, Math.floor(clickX / self.tickWidth));
        var snap = self.snapTicks || 1;
        var noteStartTick = Math.floor(clickedTick / snap) * snap;
        var clickedPitch = MAX_PITCH - Math.floor(clickY / self.rowHeight);
        clickedPitch = Math.max(MIN_PITCH, Math.min(MAX_PITCH, clickedPitch));

        var newNote = {
          id: Date.now(),
          voice: self.currentVoice,
          pitch: clickedPitch,
          startTick: noteStartTick,
          durationTicks: snap
        };

        self.model.notes.push(newNote);
        self.selectedNoteId = newNote.id;
        playTone(clickedPitch, 0.25, self.currentVoice);
        self.commitEdit();
      });

      // Double click note to delete
      gridEl.addEventListener('dblclick', function (e) {
        var noteEl = e.target.closest('.roll-note');
        if (noteEl && !noteEl.classList.contains('ghost')) {
          e.preventDefault();
          e.stopPropagation();
          var id = parseInt(noteEl.dataset.noteId, 10);
          self.deleteNote(id);
        }
      });

      function onPointerMove(e) {
        if (!dragState) { return; }
        var snap = self.snapTicks || 1;

        if (dragState.type === 'resize') {
          var deltaX = e.clientX - dragState.startX;
          var deltaTicks = Math.round(deltaX / self.tickWidth);
          var newDur = Math.max(snap, Math.round((dragState.origDuration + deltaTicks) / snap) * snap);
          if (newDur !== dragState.note.durationTicks) {
            dragState.note.durationTicks = newDur;
            self.renderNotes();
          }
        } else if (dragState.type === 'move') {
          var dX = e.clientX - dragState.startX;
          var dY = e.clientY - dragState.startY;
          var dTicks = Math.round(dX / self.tickWidth);
          var dPitch = -Math.round(dY / self.rowHeight);

          var newStart = Math.max(0, Math.round((dragState.origStartTick + dTicks) / snap) * snap);
          var newPitch = Math.max(MIN_PITCH, Math.min(MAX_PITCH, dragState.origPitch + dPitch));

          var changed = false;
          if (newStart !== dragState.note.startTick) {
            dragState.note.startTick = newStart;
            changed = true;
          }
          if (newPitch !== dragState.note.pitch) {
            dragState.note.pitch = newPitch;
            changed = true;
            if (newPitch !== dragState.lastPitch) {
              playTone(newPitch, 0.15, self.currentVoice);
              dragState.lastPitch = newPitch;
            }
          }
          if (changed) {
            self.renderNotes();
          }
        }
      }

      function onPointerUp() {
        if (!dragState) { return; }
        dragState = null;
        window.removeEventListener('pointermove', onPointerMove);
        window.removeEventListener('pointerup', onPointerUp);
        self.commitEdit();
      }
    },

    findNote: function (id) {
      if (!this.model) { return null; }
      for (var i = 0; i < this.model.notes.length; i++) {
        if (this.model.notes[i].id === id) { return this.model.notes[i]; }
      }
      return null;
    },

    deleteNote: function (id) {
      if (!this.model) { return; }
      this.model.notes = this.model.notes.filter(function (n) { return n.id !== id; });
      if (this.selectedNoteId === id) { this.selectedNoteId = null; }
      this.commitEdit();
    },

    deleteSelectedNote: function () {
      if (this.selectedNoteId) {
        this.deleteNote(this.selectedNoteId);
      }
    },

    scrollToNotes: function () {
      if (!this.model || this.model.notes.length === 0) {
        // Default scroll to C4 / C5 area
        var centerTop = (MAX_PITCH - 65) * this.rowHeight - 150;
        var gridScroll = document.getElementById('roll-grid-scroll');
        if (gridScroll) { gridScroll.scrollTop = Math.max(0, centerTop); }
        return;
      }
      var sumPitch = 0;
      var count = 0;
      for (var i = 0; i < this.model.notes.length; i++) {
        sumPitch += this.model.notes[i].pitch;
        count++;
      }
      var avgPitch = Math.round(sumPitch / count);
      var rowTop = (MAX_PITCH - avgPitch) * this.rowHeight;
      var scrollEl = document.getElementById('roll-grid-scroll');
      if (scrollEl) {
        var viewH = scrollEl.clientHeight || 400;
        scrollEl.scrollTop = Math.max(0, rowTop - viewH / 2);
      }
    },

    /* ------------------------------------------------ Transport & Playback */
    togglePlay: function () {
      if (this.isPlaying) {
        this.stop();
      } else {
        this.play();
      }
    },

    play: function () {
      if (!this.model) { return; }
      this.stop();

      var ctx = getAudioContext();
      if (ctx && ctx.state === 'suspended') {
        ctx.resume().catch(function () {});
      }

      var ticksPerBar = this.model.ticksPerBar || 16;
      var unitLength = this.model.unitLength || 16;
      var bpm = this.model.bpm || 120;
      var ticksPerBeat = Math.max(1, unitLength / 4);
      var secondsPerTick = (60 / bpm) / ticksPerBeat;
      var totalTicks = this.getTotalTicks();

      if (this.playheadTick >= totalTicks) {
        this.playheadTick = 0;
      }

      this.isPlaying = true;
      var playBtn = document.getElementById('roll-play');
      if (playBtn) {
        playBtn.textContent = '⏸ Pause';
        playBtn.title = 'Pause (Space)';
      }

      var self = this;
      var startTick = this.playheadTick;
      var startTime = performance.now();
      var baseAudioTime = (ctx ? ctx.currentTime : 0) + 0.05;
      var LOOKAHEAD_TICKS = Math.max(8, Math.ceil(0.5 / secondsPerTick));
      var scheduledUpToTick = startTick;

      function scheduleNotes(fromTick, toTick) {
        if (!ctx || !self.model || !self.model.notes) { return; }
        for (var i = 0; i < self.model.notes.length; i++) {
          var note = self.model.notes[i];
          if (note.startTick >= fromTick && note.startTick < toTick) {
            var noteOffsetSec = (note.startTick - startTick) * secondsPerTick;
            var targetAudioTime = baseAudioTime + noteOffsetSec;
            if (targetAudioTime < ctx.currentTime) {
              targetAudioTime = ctx.currentTime;
            }
            var noteDur = note.durationTicks * secondsPerTick;
            playTone(note.pitch, noteDur, note.voice, targetAudioTime);
          }
        }
      }

      // Schedule initial chunk
      scheduleNotes(startTick, startTick + LOOKAHEAD_TICKS);
      scheduledUpToTick = startTick + LOOKAHEAD_TICKS;

      // Visual animation & scheduling loop
      function tickLoop() {
        if (!self.isPlaying) { return; }
        var now = performance.now();
        var elapsedSec = (now - startTime) / 1000;
        var currentTick = startTick + (elapsedSec / secondsPerTick);

        if (currentTick >= totalTicks) {
          self.stop();
          self.seekTick(0);
          return;
        }

        var lookaheadTick = currentTick + LOOKAHEAD_TICKS;
        if (lookaheadTick > scheduledUpToTick) {
          scheduleNotes(scheduledUpToTick, lookaheadTick);
          scheduledUpToTick = lookaheadTick;
        }

        self.playheadTick = Math.floor(currentTick);
        self.updatePlayhead(currentTick);
        self.playTimer = requestAnimationFrame(tickLoop);
      }

      this.playTimer = requestAnimationFrame(tickLoop);
      this.updatePlayhead(startTick);
    },

    stop: function () {
      this.isPlaying = false;
      if (this.playTimer) {
        cancelAnimationFrame(this.playTimer);
        this.playTimer = null;
      }
      stopAllAudio();
      if (typeof document !== 'undefined') {
        var playBtn = document.getElementById('roll-play');
        if (playBtn) {
          playBtn.textContent = '▶ Play';
          playBtn.title = 'Play (Space)';
        }
      }
      this.updatePlayhead();
    },

    seekTick: function (tick) {
      var wasPlaying = this.isPlaying;
      if (wasPlaying) {
        this.stop();
      }
      this.playheadTick = Math.max(0, tick);
      this.updatePlayhead();
      this.ensurePlayheadVisible();
      if (wasPlaying) {
        this.play();
      }
    },

    stepPrev: function () {
      var ticksPerBar = (this.model && this.model.ticksPerBar) || 16;
      var curBar = Math.floor(this.playheadTick / ticksPerBar);
      var inBar = this.playheadTick % ticksPerBar;
      var targetBar = inBar > 0 ? curBar : Math.max(0, curBar - 1);
      this.seekTick(targetBar * ticksPerBar);
    },

    stepNext: function () {
      var ticksPerBar = (this.model && this.model.ticksPerBar) || 16;
      var curBar = Math.floor(this.playheadTick / ticksPerBar);
      var targetBar = curBar + 1;
      this.seekTick(targetBar * ticksPerBar);
    },

    rewindToStart: function () {
      this.seekTick(0);
    },

    ensurePlayheadVisible: function () {
      if (typeof document === 'undefined') { return; }
      var scrollEl = document.getElementById('roll-grid-scroll');
      if (!scrollEl) { return; }
      var left = this.playheadTick * this.tickWidth;
      var viewW = scrollEl.clientWidth || 600;
      var curScroll = scrollEl.scrollLeft;
      if (left < curScroll || left > curScroll + viewW - 60) {
        scrollEl.scrollLeft = Math.max(0, left - 60);
      }
    },

    updatePlayhead: function (continuousTick) {
      if (typeof document === 'undefined') { return; }
      var playhead = document.getElementById('roll-playhead');
      var rulerPlayhead = document.getElementById('roll-ruler-playhead');
      var timeEl = document.getElementById('roll-time');
      var ticksPerBar = (this.model && this.model.ticksPerBar) || 16;
      var unitLength = (this.model && this.model.unitLength) || 16;
      var bpm = (this.model && this.model.bpm) || 120;
      var ticksPerBeat = Math.max(1, unitLength / 4);
      var secondsPerTick = (60 / bpm) / ticksPerBeat;

      var curTick = continuousTick !== undefined ? continuousTick : this.playheadTick;
      var left = curTick * this.tickWidth;

      if (playhead) {
        playhead.style.left = left + 'px';
      }
      if (rulerPlayhead) {
        rulerPlayhead.style.left = left + 'px';
      }

      if (timeEl) {
        var intTick = Math.max(0, Math.floor(curTick));
        var barNum = Math.floor(intTick / ticksPerBar) + 1;
        var beatNum = Math.floor((intTick % ticksPerBar) / (ticksPerBar / 4)) + 1;
        var totalSec = Math.floor(intTick * secondsPerTick);
        var mins = Math.floor(totalSec / 60);
        var secs = totalSec % 60;
        var timeStr = mins + ':' + (secs < 10 ? '0' : '') + secs;
        timeEl.textContent = barNum + '.' + beatNum + ' (' + timeStr + ')';
      }

      if (this.isPlaying) {
        var scrollEl = document.getElementById('roll-grid-scroll');
        if (scrollEl) {
          var viewW = scrollEl.clientWidth || 600;
          var curScroll = scrollEl.scrollLeft;
          if (left > curScroll + viewW - 80) {
            scrollEl.scrollLeft = left - 60;
          } else if (left < curScroll) {
            scrollEl.scrollLeft = Math.max(0, left - 60);
          }
        }
      }
    },

    /* ------------------------------------------------ Commit Changes */
    commitEdit: function () {
      if (!this.model) { return; }
      var newAbc = serializeToAbc(this.model);
      this.renderAll();

      // Notify external subscribers (e.g. app.js)
      for (var i = 0; i < this.listeners.length; i++) {
        try {
          this.listeners[i](newAbc);
        } catch (err) {
          console.error("PianoRoll listener error:", err);
        }
      }
    },

    onUpdate: function (cb) {
      this.listeners.push(cb);
    }
  };

  global.PianoRoll = PianoRoll;
  global.parseAbc = parseAbc;
  global.serializeToAbc = serializeToAbc;

})(typeof window !== 'undefined' ? window : this);

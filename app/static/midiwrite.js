/**
 * The Score window's MIDI file, written from the sequence abcjs builds to play a score.
 *
 * abcjs can write a MIDI file itself (ABCJS.synth.getMidiFile), but its writer does sums on the
 * drum pitches and volumes, which reach it as strings, so a score with drums came out with
 * pitches like 54 and 56 and a velocity of 128 (not a legal MIDI data byte). It also puts every
 * track's instrument on channel 1 whatever channel the notes are on, and never gives the bass
 * an instrument of its own. The sequence that plays the preview has none of those faults: every
 * note carries its own instrument, pitch and volume. So the file is written from that.
 *
 * What comes out is a type 1 file (480 ticks to a quarter note): a tempo track, then one track
 * for each part, each on a channel of its own with its instrument set on that channel, the
 * drums on channel 10, and every data byte kept in 0..127.
 */
(function (global) {
  'use strict';

  var TICKS_PER_QUARTER = 480;
  var TICKS_PER_WHOLE = TICKS_PER_QUARTER * 4;     // abcjs counts start and duration in whole notes
  var DRUM_CHANNEL = 9;                            // channel 10, counting from one
  var DRUM_INSTRUMENT = 128;                       // abcjs's number for the percussion set

  function clampInt(value, low, high, fallback) {
    var n = Math.round(Number(value));
    if (!isFinite(n)) { n = fallback; }
    return Math.min(high, Math.max(low, n));
  }

  // push.apply has a limit on how many arguments it takes, which a long song's track can pass.
  function append(target, source) {
    for (var i = 0; i < source.length; i++) { target.push(source[i]); }
  }

  function varLength(value) {
    var n = Math.max(0, Math.floor(value));
    var bytes = [n & 0x7f];
    n = Math.floor(n / 128);
    while (n > 0) { bytes.unshift((n & 0x7f) | 0x80); n = Math.floor(n / 128); }
    return bytes;
  }

  function text(string) {
    var out = [];
    for (var i = 0; i < string.length; i++) {
      var code = string.charCodeAt(i);
      out.push(code < 128 ? code : 63);            // a data byte cannot be above 127
    }
    return out;
  }

  function meta(type, bytes) { return [0xff, type].concat(varLength(bytes.length), bytes); }

  function trackName(name) { return meta(0x03, text(String(name || ''))); }

  function tempoEvent(quartersPerMinute) {
    var qpm = Number(quartersPerMinute);
    if (!isFinite(qpm) || qpm <= 0) { qpm = 120; }
    var micros = Math.min(0xffffff, Math.max(1, Math.round(60000000 / qpm)));
    return meta(0x51, [(micros >> 16) & 0xff, (micros >> 8) & 0xff, micros & 0xff]);
  }

  function meterEvent(meter) {
    var num = meter && Number(meter.num) > 0 ? Math.round(Number(meter.num)) : 4;
    var den = meter && Number(meter.den) > 0 ? Math.round(Number(meter.den)) : 4;
    var power = Math.max(0, Math.min(7, Math.round(Math.log(den) / Math.log(2))));
    return meta(0x58, [Math.min(127, num), power, 24, 8]);
  }

  // A track: its events as {tick, order, bytes}, written with delta times. Note-offs sort before
  // note-ons at the same tick so a repeated note is not cut short by its own earlier end.
  function trackBytes(events) {
    events.sort(function (a, b) { return a.tick - b.tick || a.order - b.order; });
    var body = [];
    var last = 0;
    events.forEach(function (event) {
      append(body, varLength(event.tick - last));
      append(body, event.bytes);
      last = event.tick;
    });
    append(body, varLength(0));
    append(body, meta(0x2f, []));
    var n = body.length;
    var out = [0x4d, 0x54, 0x72, 0x6b, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff];
    append(out, body);
    return out;
  }

  function noteEvents(notes, channel) {
    var events = [];
    notes.forEach(function (note) {
      var pitch = clampInt(note.pitch, 0, 127, 60);
      var velocity = clampInt(note.volume, 1, 127, 80);
      var start = clampInt(Number(note.start) * TICKS_PER_WHOLE, 0, 0x7fffffff, 0);
      var length = Math.max(1, clampInt(Number(note.duration) * TICKS_PER_WHOLE, 1, 0x7fffffff, 1));
      events.push({ tick: start, order: 1, bytes: [0x90 | channel, pitch, velocity] });
      events.push({ tick: start + length, order: 0, bytes: [0x80 | channel, pitch, 0] });
    });
    return events;
  }

  function mean(list) {
    return list.length ? list.reduce(function (a, b) { return a + b; }, 0) / list.length : 0;
  }

  /**
   * seq: what tune.setUpAudio(options) returns: { tempo, tracks: [[event, ...], ...] }, where an
   *      event is { cmd: 'note' | 'program' | 'text' | 'tempo', ... }.
   * info: { meter: { num, den }, title }, both optional.
   * Returns a Uint8Array holding the file, or null when the score has no notes.
   */
  function writeMidi(seq, info) {
    info = info || {};
    var tracks = (seq && seq.tracks) || [];
    var conductor = [];
    var tempoChanges = [];
    var parts = [];                                 // { name, instrument, notes, drums }

    tracks.forEach(function (events, index) {
      var name = '';
      var byInstrument = [];                        // in the order first seen
      var seen = {};
      (events || []).forEach(function (event) {
        if (!event) { return; }
        if (event.cmd === 'text' && event.type === 'name' && !name) { name = String(event.text || ''); }
        if (event.cmd === 'tempo' && Number(event.qpm) > 0) {
          tempoChanges.push({ tick: clampInt(Number(event.start) * TICKS_PER_WHOLE, 0, 0x7fffffff, 0), qpm: Number(event.qpm) });
        }
        if (event.cmd !== 'note') { return; }
        var instrument = event.instrument === undefined || event.instrument === null ? 0 : Number(event.instrument);
        if (!seen.hasOwnProperty(instrument)) { seen[instrument] = byInstrument.length; byInstrument.push({ instrument: instrument, notes: [] }); }
        byInstrument[seen[instrument]].notes.push(event);
      });
      if (!byInstrument.length) { return; }
      // A track whose notes use more than one instrument is the chords with their bass: the lower
      // part goes to a track of its own, so the bass can have the instrument the style chose.
      var several = byInstrument.length > 1;
      byInstrument.sort(function (a, b) {
        var pa = mean(a.notes.map(function (n) { return Number(n.pitch); }));
        var pb = mean(b.notes.map(function (n) { return Number(n.pitch); }));
        return several ? pb - pa : 0;               // the higher part first
      });
      byInstrument.forEach(function (group, at) {
        var drums = group.instrument === DRUM_INSTRUMENT;
        var label = name;
        if (!label) { label = drums ? 'Drums' : (several ? (at === 0 ? 'Chords' : 'Bass') : 'Part ' + (index + 1)); }
        else if (several) { label = name + (at === 0 ? '' : ' (bass)'); }
        parts.push({ name: label, instrument: group.instrument, notes: group.notes, drums: drums });
      });
    });

    if (!parts.length) { return null; }

    conductor.push({ tick: 0, order: 0, bytes: trackName(info.title || 'Score') });
    conductor.push({ tick: 0, order: 0, bytes: meterEvent(info.meter) });
    conductor.push({ tick: 0, order: 0, bytes: tempoEvent(seq.tempo) });
    tempoChanges.forEach(function (change) { conductor.push({ tick: change.tick, order: 0, bytes: tempoEvent(change.qpm) }); });

    var channel = 0;
    var written = [trackBytes(conductor)];
    parts.forEach(function (part) {
      var use;
      if (part.drums) { use = DRUM_CHANNEL; }
      else {
        if (channel === DRUM_CHANNEL) { channel++; }
        use = Math.min(15, channel++);
      }
      var events = [{ tick: 0, order: 0, bytes: trackName(part.name) }];
      if (!part.drums) { events.push({ tick: 0, order: 0, bytes: [0xc0 | use, clampInt(part.instrument, 0, 127, 0)] }); }
      written.push(trackBytes(events.concat(noteEvents(part.notes, use))));
    });

    var count = written.length;
    var header = [0x4d, 0x54, 0x68, 0x64, 0, 0, 0, 6, 0, 1, (count >> 8) & 0xff, count & 0xff,
                  (TICKS_PER_QUARTER >> 8) & 0xff, TICKS_PER_QUARTER & 0xff];
    var all = header.slice();
    written.forEach(function (bytes) { append(all, bytes); });
    return new Uint8Array(all);
  }

  global.writeMidi = writeMidi;

})(typeof window !== 'undefined' ? window : this);

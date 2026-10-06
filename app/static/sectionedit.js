/**
 * Rearranging the sections of a score.
 *
 * A transcribed score names each of its sections on a "% name" line, and every section is a block of its
 * own: the voices it plays and its bars follow the line, under a header (tempo, key, voices) that they
 * share. So a section can be moved, copied or taken out by moving the block, and the score that results
 * is still the score of a song. This works on the text only; the page shows the result and the render
 * plays it as it plays any score.
 */
(function (global) {
  'use strict';

  var MARK = /^%[ \t]*([A-Za-z][\w -]*?)[ \t]*$/gm;       // the same lines the section list reads

  // The header, and each section's text from its "%" line up to the next one.
  function parse(abc) {
    var text = String(abc || '');
    var at = [];
    var found;
    MARK.lastIndex = 0;
    while ((found = MARK.exec(text))) { at.push(found.index); }
    if (!at.length) { return { head: text, parts: [], endsWithNewline: /\n$/.test(text) }; }
    var parts = at.map(function (start, i) { return text.slice(start, i + 1 < at.length ? at[i + 1] : text.length); });
    return { head: text.slice(0, at[0]), parts: parts, endsWithNewline: /\n$/.test(text) };
  }

  function build(head, parts, endsWithNewline) {
    var out = head + parts.map(function (part) { return /\n$/.test(part) ? part : part + '\n'; }).join('');
    return endsWithNewline ? out : out.replace(/\n$/, '');
  }

  /**
   * op: { act: 'up' | 'down' | 'copy' | 'remove' | 'move', index, to }; 'move' puts section `index` at position `to`
   * (counted after it has been lifted out, so `to` is where it ends up). Returns the new score, or null when the
   * move cannot be made (off either end, no such section, or the last section left).
   */
  function change(abc, op) {
    var score = parse(abc);
    var parts = score.parts.slice();
    var i = Number(op && op.index);
    if (!parts.length || !(i >= 0 && i < parts.length) || Math.floor(i) !== i) { return null; }
    if (op.act === 'up') {
      if (i === 0) { return null; }
      parts.splice(i - 1, 2, parts[i], parts[i - 1]);
    } else if (op.act === 'down') {
      if (i === parts.length - 1) { return null; }
      parts.splice(i, 2, parts[i + 1], parts[i]);
    } else if (op.act === 'copy') {
      parts.splice(i + 1, 0, parts[i]);
    } else if (op.act === 'move') {
      var to = Number(op.to);
      if (!(to >= 0 && to < parts.length) || Math.floor(to) !== to || to === i) { return null; }
      parts.splice(to, 0, parts.splice(i, 1)[0]);
    } else if (op.act === 'remove') {
      if (parts.length < 2) { return null; }
      parts.splice(i, 1);
    } else {
      return null;
    }
    return build(score.head, parts, score.endsWithNewline);
  }

  global.ScoreSections = { parse: parse, change: change };
  if (typeof module !== 'undefined' && module.exports) { module.exports = global.ScoreSections; }

})(typeof window !== 'undefined' ? window : this);

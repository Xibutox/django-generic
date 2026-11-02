/**
 * Tables that scroll in a frame of the window's height.
 *
 * A long table's rows scroll inside their own box, its header pinned
 * at the top of that box (``position: sticky`` in the stylesheets).
 * The box is sized so that the whole card - the toolbar above it
 * (search, filters, columns, export, the selection bar), the header,
 * the rows and the paging under it - fits in the window under the top
 * bar: scrolled to, a table shows its menus and its headers together,
 * however far down its rows one reads.
 *
 * The frames: a data table's (``.dt-layout-table > .dt-layout-cell``)
 * and a tree's (``.tree__scroll``). One marked ``data-table-frame="false"``
 * keeps its full height; so does one inside a dialog, which scrolls
 * itself. A short table is never stretched: the height is a maximum.
 * Without this script the frames keep their full height, as before.
 */
(function (window, document) {
  "use strict";

  var FRAMES = ".dt-layout-table > .dt-layout-cell, .tree__scroll";
  // The card around the frame: its toolbar and paging count with it.
  var CARDS = ".module, .card, .dt-container";
  // Under this, a frame shows too few rows to read: the page scrolls
  // instead (a phone held sideways).
  var MIN_ROWS_HEIGHT = 12;
  var pending = false;

  function rem(value) {
    var size = parseFloat(
      window.getComputedStyle(document.documentElement).fontSize
    );

    return value * (size || 16);
  }

  function headerHeight() {
    var bar = document.querySelector(".topbar");

    if (!bar) {
      return 0;
    }

    var position = window.getComputedStyle(bar).position;

    return position === "sticky" || position === "fixed"
      ? bar.offsetHeight
      : 0;
  }

  function release(frame) {
    if (frame.style.maxHeight) {
      frame.style.maxHeight = "";
    }
  }

  function size(frame, room) {
    if (
      frame.dataset.tableFrame === "false" ||
      frame.closest("dialog, .dialog, [role=dialog]")
    ) {
      release(frame);
      return;
    }

    var card = frame.parentElement.closest(CARDS) || frame.parentElement;
    var outer = card.getBoundingClientRect();
    var inner = frame.getBoundingClientRect();

    // Hidden (a closed tab, a folded panel): measured when shown.
    if (inner.height === 0 && inner.width === 0) {
      return;
    }

    // What the card holds besides the frame keeps its height whatever
    // the frame's, so measuring with the current maximum is stable.
    var around = outer.height - inner.height;
    var height = Math.floor(room - around);

    if (height < rem(MIN_ROWS_HEIGHT)) {
      release(frame);
      return;
    }

    var value = height + "px";

    if (frame.style.maxHeight !== value) {
      frame.style.maxHeight = value;
    }
  }

  function update() {
    pending = false;

    // The window under the top bar, less a margin each side so the
    // card's edges show.
    var room = window.innerHeight - headerHeight() - rem(2);

    document.querySelectorAll(FRAMES).forEach(function (frame) {
      size(frame, room);
    });
  }

  function schedule() {
    if (!pending) {
      pending = true;
      window.requestAnimationFrame(update);
    }
  }

  function start() {
    window.addEventListener("resize", schedule, { passive: true });

    // A table drawn, a search row or a selection bar shown, a tab
    // opened: the page changes size without the window doing so.
    if (typeof window.ResizeObserver === "function") {
      new window.ResizeObserver(schedule).observe(document.body);
    }

    schedule();
  }

  window.Generic = window.Generic || {};
  window.Generic.tableFrame = { update: schedule };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window, document);

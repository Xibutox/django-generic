/**
 * Records on a calendar (generic.sites.calendars): a month, a week, a
 * day, or the days of a month as a list.
 *
 * The page asks the calendar's endpoint for the days it shows, and
 * again when they change, when the table above it is filtered or
 * searched, or when a record of the resource changes. With moveUrl, a
 * record dragged onto another day is written there.
 *
 * With config.hours, the week and the day are drawn as hours: a record
 * at its time, as tall as it lasts. It is dragged to another time
 * (snapped to config.step minutes), its lower edge dragged to change
 * its end; a stretch of empty hours dragged across opens the add form,
 * in a window of its own, with the start and the end filled in. With
 * config.allocate, records of a relation are listed beside the hours,
 * and one dropped on a time creates a record pointing at it there.
 *
 *   <div class="generic-calendar" data-config="<id of a json_script>"></div>
 *   Generic.calendar.start(element)
 *
 * Days are handled as UTC dates ("2026-10-07" is that day wherever the
 * browser is): the server already placed each record on its days, in
 * the reader's zone. Every value reaches the page through textContent,
 * every address through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var values = Generic.values;
  var el = values.el;
  var icon = values.icon;

  var DAY = 86400000;
  var SHOWN_PER_DAY = 4;
  var MINUTE = 60000;
  var VIEW_ICONS = { month: "calendar_view_month", week: "calendar_view_week", day: "calendar_view_day", list: "view_agenda" };
  var VIEW_LABELS = { month: t("Month"), week: t("Week"), day: t("Day"), list: t("List") };
  //: What the add form's window posts back once it saved (forms/form.js).
  var SAVED_MESSAGE = "generic:relation-saved";

  function readJson(id) {
    var element = document.getElementById(id);

    if (!element) {
      return null;
    }

    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      return null;
    }
  }

  /* -- Days ----------------------------------------------------------- */

  function parseDay(text) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");

    return match ? new Date(Date.UTC(+match[1], +match[2] - 1, +match[3])) : null;
  }

  function iso(day) {
    return day.toISOString().slice(0, 10);
  }

  function addDays(day, count) {
    return new Date(day.getTime() + count * DAY);
  }

  function startOfMonth(day) {
    return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), 1));
  }

  function addMonths(day, count) {
    return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth() + count, 1));
  }

  /** "2026-10-07T09:30", the reader's wall clock, as a UTC instant -
   * as days are. */
  function parseMoment(text) {
    var match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(text || "");

    return match ? new Date(Date.UTC(+match[1], +match[2] - 1, +match[3], +match[4], +match[5])) : null;
  }

  function moment(day, minutes) {
    return new Date(day.getTime() + minutes * MINUTE).toISOString().slice(0, 16);
  }

  function pad(number) {
    return (number < 10 ? "0" : "") + number;
  }

  function clock(minutes) {
    var whole = Math.round(minutes);

    return pad(Math.floor(whole / 60) % 24) + ":" + pad(whole % 60);
  }

  /** A length of time: "45 min", "2 h", "7 h 30". */
  function lasting(minutes) {
    var hours = Math.floor(minutes / 60);
    var rest = Math.round(minutes - hours * 60);

    if (!hours) {
      return Generic.format(t("%(minutes)s min"), { minutes: rest });
    }

    return rest
      ? Generic.format(t("%(hours)s h %(minutes)s"), { hours: hours, minutes: pad(rest) })
      : Generic.format(t("%(hours)s h"), { hours: hours });
  }

  function language() {
    return document.documentElement.lang || undefined;
  }

  function format(day, options) {
    try {
      return new Intl.DateTimeFormat(language(), Object.assign({ timeZone: "UTC" }, options)).format(day);
    } catch (error) {
      return iso(day);
    }
  }

  /* -- The calendar ------------------------------------------------------ */

  function CalendarView(element, config) {
    var params = new URLSearchParams(window.location.search);

    this.element = element;
    this.config = config;
    this.views = config.views && config.views.length ? config.views : ["month"];
    this.view = this.views.indexOf(params.get("view")) !== -1 ? params.get("view") : this.views[0];
    this.today = parseDay(config.today) || parseDay(iso(new Date()));
    this.anchor = parseDay(params.get("date")) || this.today;
    this.tableFilters = { filters: "", search: "" };
    this.events = [];
    this.asking = null;
    this.build();
  }

  CalendarView.prototype.build = function () {
    var self = this;
    var toolbar = el("div", "calendar__toolbar");
    var moves = el("div", "calendar__moves");
    var switcher = el("div", "calendar__views");

    function button(iconName, label, onClick, extra) {
      var element = el("button", "button button--sm button--ghost" + (extra ? " " + extra : ""));

      element.type = "button";

      if (iconName) {
        element.appendChild(icon(iconName));
      }

      if (label) {
        element.appendChild(el("span", "", label));
      }

      element.addEventListener("click", onClick);

      return element;
    }

    var previous = button("chevron_left", "", function () {
      self.go(-1);
    });
    var next = button("chevron_right", "", function () {
      self.go(1);
    });

    previous.setAttribute("aria-label", t("Previous"));
    previous.title = t("Previous");
    next.setAttribute("aria-label", t("Next"));
    next.title = t("Next");

    moves.appendChild(previous);
    moves.appendChild(
      button("today", t("Today"), function () {
        self.anchor = self.today;
        self.refresh();
      })
    );
    moves.appendChild(next);

    this.title = el("h2", "calendar__title");
    this.status = el("span", "calendar__status muted");
    this.status.setAttribute("aria-live", "polite");

    this.viewButtons = {};
    this.views.forEach(function (view) {
      var element = button(VIEW_ICONS[view], VIEW_LABELS[view], function () {
        self.view = view;
        self.refresh();
      });

      self.viewButtons[view] = element;
      switcher.appendChild(element);
    });

    toolbar.appendChild(moves);
    toolbar.appendChild(this.title);
    toolbar.appendChild(this.status);

    if (this.views.length > 1) {
      toolbar.appendChild(switcher);
    }

    this.body = el("div", "calendar__body");
    this.element.textContent = "";
    this.element.appendChild(toolbar);

    if (this.config.allocate) {
      var layout = el("div", "calendar__layout");

      this.panel = this.buildPanel();
      layout.appendChild(this.body);
      layout.appendChild(this.panel);
      this.element.appendChild(layout);
    } else {
      this.element.appendChild(this.body);
    }

    window.addEventListener("message", function (event) {
      self.saved(event);
    });
  };

  /** An hourly calendar is drawn as hours in the week and the day. */
  CalendarView.prototype.hourly = function () {
    return !!(this.config.hours && (this.view === "week" || this.view === "day"));
  };

  /** The days shown: [start, end), and the heading saying which. */
  CalendarView.prototype.range = function () {
    var first = this.config.firstDay || 0;

    if (this.view === "day") {
      return {
        start: this.anchor,
        end: addDays(this.anchor, 1),
        title: format(this.anchor, { weekday: "long", day: "numeric", month: "long", year: "numeric" })
      };
    }

    if (this.view === "week") {
      var offset = (this.anchor.getUTCDay() - first + 7) % 7;
      var monday = addDays(this.anchor, -offset);
      var sunday = addDays(monday, 6);

      return {
        start: monday,
        end: addDays(monday, 7),
        title: format(monday, { day: "numeric", month: "short" }) + " \u2013 " + format(sunday, { day: "numeric", month: "short", year: "numeric" })
      };
    }

    var month = startOfMonth(this.anchor);
    var title = format(month, { month: "long", year: "numeric" });

    if (this.view === "list") {
      return { start: month, end: addMonths(month, 1), title: title, month: month };
    }

    var lead = (month.getUTCDay() - first + 7) % 7;
    var start = addDays(month, -lead);

    return { start: start, end: addDays(start, 42), title: title, month: month };
  };

  CalendarView.prototype.go = function (step) {
    if (this.view === "week") {
      this.anchor = addDays(this.anchor, 7 * step);
    } else if (this.view === "day") {
      this.anchor = addDays(this.anchor, step);
    } else {
      this.anchor = addMonths(this.anchor, step);
    }

    this.refresh();
  };

  /** Keep the address saying what is shown, so it can be bookmarked. */
  CalendarView.prototype.writeLink = function () {
    if (!window.history || !window.history.replaceState) {
      return;
    }

    var url = new URL(window.location.href);

    url.searchParams.set("view", this.view);
    url.searchParams.set("date", iso(this.anchor));
    window.history.replaceState(window.history.state, "", url.toString());
  };

  CalendarView.prototype.refresh = function () {
    var self = this;
    var shown = this.range();
    var params = { start: iso(shown.start), end: iso(shown.end) };
    var asked = {};

    Object.keys(this.viewButtons).forEach(function (view) {
      self.viewButtons[view].classList.toggle("is-active", view === self.view);
      self.viewButtons[view].setAttribute("aria-pressed", view === self.view ? "true" : "false");
    });

    if (this.tableFilters.filters) {
      params.filters = this.tableFilters.filters;
    }

    if (this.tableFilters.search) {
      params.search = this.tableFilters.search;
    }

    this.shown = shown;
    this.title.textContent = shown.title;
    this.status.textContent = t("Loading\u2026");
    this.asking = asked;
    this.writeLink();

    return Generic.api
      .get(this.config.url, params)
      .then(function (answer) {
        // Moved on meanwhile: that answer draws instead.
        if (self.asking !== asked) {
          return;
        }

        self.events = answer.events || [];
        self.draw();

        var count = self.events.length;
        var status = count
          ? Generic.format(Generic.nt("%(count)s record", "%(count)s records", count), { count: count })
          : t("Nothing on these days.");

        if (answer.truncated) {
          status += " " + t("(the first ones only: filter the table)");
        }

        self.status.textContent = status;
      })
      .catch(function (error) {
        if (self.asking === asked) {
          self.status.textContent = "";
          Generic.toast((error && error.message) || t("The calendar could not be loaded."), "error");
        }
      });
  };

  /** Each day of the range, with the records falling on it. */
  CalendarView.prototype.byDay = function () {
    var days = {};
    var shown = this.shown;

    this.events.forEach(function (event) {
      var first = parseDay(event.start);
      var last = parseDay(event.end) || first;

      if (!first) {
        return;
      }

      var day = first < shown.start ? shown.start : first;

      for (; day <= last && day < shown.end; day = addDays(day, 1)) {
        var key = iso(day);

        (days[key] = days[key] || []).push({
          event: event,
          continued: day > first,
          continues: day < last
        });
      }
    });

    return days;
  };

  CalendarView.prototype.draw = function () {
    this.body.textContent = "";

    if (this.panel) {
      // Records are dropped on hours - or, on a calendar of days, on
      // a day of the month or the week.
      var shown = this.hourly() || (!this.config.timed && this.view !== "list");

      this.panel.hidden = !shown;
      this.element.classList.toggle("calendar--allocating", shown);
    }

    if (this.view === "list") {
      this.drawList();
    } else if (this.hourly()) {
      this.drawHours();
    } else {
      this.drawGrid();
    }
  };

  /* -- An event ------------------------------------------------------------ */

  CalendarView.prototype.chip = function (placed, detailed) {
    var self = this;
    var event = placed.event;
    var colour = Generic.colors.clean(event.background) || Generic.colors.clean(event.color);
    var linked = event.url && Generic.isSafeUrl(event.url);
    // Detailed, its values hold links of their own: the label is the
    // link then, as links never nest.
    var chip = el(linked && !detailed ? "a" : "div", "calendar-event");

    if (chip.tagName === "A") {
      chip.href = event.url;
    }

    if (colour) {
      chip.style.setProperty("--event-color", colour);
    }

    if (placed.continued) {
      chip.classList.add("calendar-event--continued");
    }

    if (placed.continues) {
      chip.classList.add("calendar-event--continues");
    }

    if (event.time && !placed.continued) {
      chip.appendChild(el("span", "calendar-event__time", event.time));
    }

    var label = detailed && linked ? values.link(event.url, event.label) : el("span", "", event.label);

    label.classList.add("calendar-event__label");
    chip.appendChild(label);
    chip.title = [event.time, event.label]
      .concat(
        (event.cells || []).map(function (entry) {
          return entry.empty ? "" : entry.label + ": " + (entry.display || (entry.items || []).map(function (item) {
            return item.label;
          }).join(", "));
        })
      )
      .filter(Boolean)
      .join("\n");

    if (detailed && (event.cells || []).length) {
      var cells = el("span", "calendar-event__cells");

      event.cells.forEach(function (entry) {
        if (!entry.empty) {
          cells.appendChild(values.render(entry));
        }
      });
      chip.appendChild(cells);
    }

    if (event.editable && this.config.moveUrl) {
      chip.draggable = true;
      chip.addEventListener("dragstart", function (dragEvent) {
        dragEvent.dataTransfer.effectAllowed = "move";
        dragEvent.dataTransfer.setData("text/plain", event.id);
        self.dragging = event;
        self.element.classList.add("is-dragging");
      });
      chip.addEventListener("dragend", function () {
        self.dragging = null;
        self.element.classList.remove("is-dragging");
      });
    }

    return chip;
  };

  /** A day of the grid accepts a dragged record, and offers "Add". */
  CalendarView.prototype.dropTarget = function (cell, key) {
    var self = this;
    // A calendar of dates takes what the panel offers on its days.
    var allocating = this.config.allocate && !this.config.timed;

    if (!this.config.moveUrl && !allocating) {
      return;
    }

    function wanted() {
      return (self.dragging && self.config.moveUrl) || (allocating && self.allocating);
    }

    cell.addEventListener("dragover", function (event) {
      if (wanted()) {
        event.preventDefault();
        cell.classList.add("is-over");
      }
    });
    cell.addEventListener("dragleave", function () {
      cell.classList.remove("is-over");
    });
    cell.addEventListener("drop", function (event) {
      cell.classList.remove("is-over");

      if (!wanted()) {
        return;
      }

      event.preventDefault();

      if (self.dragging) {
        self.move(self.dragging, key);
      } else {
        self.allocate(self.allocating, key, null);
      }
    });
  };

  CalendarView.prototype.move = function (event, key) {
    var self = this;

    if (event.start === key) {
      return;
    }

    var url = this.config.moveUrl.replace("{id}", encodeURIComponent(event.id));

    Generic.api
      .patch(url, { date: key })
      .then(function () {
        Generic.toast(Generic.format(t("%(label)s moved."), { label: event.label }), "success");
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The record could not be moved."), "error");
      })
      .then(function () {
        self.refresh();
      });
  };

  CalendarView.prototype.addLink = function (key) {
    if (!this.config.addUrl || !Generic.isSafeUrl(this.config.addUrl)) {
      return null;
    }

    var link = el("a", "calendar-day__add icon-button icon-button--sm");
    var label = Generic.format(t("Add on %(day)s"), { day: format(parseDay(key), { day: "numeric", month: "long" }) });
    var url = new URL(this.config.addUrl, window.location.href);

    url.searchParams.set(this.config.dateField, key);
    link.href = url.pathname + url.search;
    link.title = label;
    link.setAttribute("aria-label", label);
    link.appendChild(icon("add"));

    return link;
  };

  /* -- Month and week ------------------------------------------------------ */

  CalendarView.prototype.drawGrid = function () {
    var self = this;
    var shown = this.shown;
    var days = this.byDay();
    var week = this.view === "week" || this.view === "day";
    var columns = this.view === "day" ? 1 : 7;
    var grid = el("div", "calendar-grid" + (week ? " calendar-grid--week" : "") + (columns === 1 ? " calendar-grid--day" : ""));
    var head = el("div", "calendar-grid__head");

    for (var index = 0; index < columns; index += 1) {
      var weekday = addDays(shown.start, index);

      var name = el("div", "calendar-grid__weekday", format(weekday, { weekday: week ? "long" : "short" }));

      name.setAttribute("role", "columnheader");
      head.appendChild(name);
    }

    head.setAttribute("role", "row");
    grid.appendChild(head);

    var body = el("div", "calendar-grid__days");
    var row = null;

    body.setAttribute("role", "rowgroup");

    // A grid's cells sit in rows: one per week, laid out by the days'
    // own grid (the row takes no box: display: contents).
    for (var day = shown.start, count = 0; day < shown.end; day = addDays(day, 1), count += 1) {
      if (count % columns === 0) {
        row = el("div", "calendar-grid__week");
        row.setAttribute("role", "row");
        body.appendChild(row);
      }

      row.appendChild(this.dayCell(day, days[iso(day)] || [], week));
    }

    grid.appendChild(body);
    grid.setAttribute("role", "grid");
    grid.setAttribute("aria-label", shown.title);
    self.body.appendChild(grid);
  };

  CalendarView.prototype.dayCell = function (day, placed, week) {
    var self = this;
    var key = iso(day);
    var cell = el("div", "calendar-day");
    var header = el("div", "calendar-day__head");
    var number = el("span", "calendar-day__number", week ? format(day, { day: "numeric", month: "short" }) : format(day, { day: "numeric" }));
    var list = el("div", "calendar-day__events");
    var add = this.addLink(key);

    cell.setAttribute("role", "gridcell");
    cell.setAttribute("data-day", key);
    cell.setAttribute("aria-label", format(day, { weekday: "long", day: "numeric", month: "long", year: "numeric" }));

    if (key === iso(this.today)) {
      cell.classList.add("calendar-day--today");
      number.setAttribute("aria-current", "date");
    }

    if (this.shown.month && day.getUTCMonth() !== this.shown.month.getUTCMonth()) {
      cell.classList.add("calendar-day--outside");
    }

    header.appendChild(number);

    if (add) {
      header.appendChild(add);
    }

    cell.appendChild(header);

    var limit = week ? placed.length : SHOWN_PER_DAY;

    placed.forEach(function (entry, index) {
      var chip = self.chip(entry, week);

      if (index >= limit) {
        chip.classList.add("calendar-event--extra");
      }

      list.appendChild(chip);
    });

    if (placed.length > limit) {
      var more = el("button", "calendar-day__more", Generic.format(t("+%(count)s more"), { count: placed.length - limit }));

      more.type = "button";
      more.addEventListener("click", function () {
        cell.classList.add("calendar-day--open");
        more.remove();
      });
      list.appendChild(more);
    }

    cell.appendChild(list);
    this.dropTarget(cell, key);

    return cell;
  };

  /* -- List ------------------------------------------------------------------ */

  CalendarView.prototype.drawList = function () {
    var self = this;
    var days = this.byDay();
    var keys = Object.keys(days).sort();
    var list = el("div", "calendar-list");

    if (!keys.length) {
      list.appendChild(el("p", "calendar-list__empty muted", t("Nothing on these days.")));
    }

    keys.forEach(function (key) {
      var day = parseDay(key);
      var section = el("section", "calendar-list__day");
      var heading = el("h3", "calendar-list__date", format(day, { weekday: "long", day: "numeric", month: "long" }));
      var events = el("div", "calendar-list__events");

      if (key === iso(self.today)) {
        section.classList.add("calendar-list__day--today");
      }

      section.appendChild(heading);
      days[key].forEach(function (entry) {
        events.appendChild(self.chip(entry, true));
      });
      section.appendChild(events);
      self.dropTarget(section, key);
      list.appendChild(section);
    });

    this.body.appendChild(list);
  };

  /* -- Hours ------------------------------------------------------------- */

  /** Each record's piece on each day shown, in minutes from midnight. */
  CalendarView.prototype.segments = function (days) {
    var step = this.config.step || 15;
    var pieces = {};

    days.forEach(function (day) {
      pieces[iso(day)] = [];
    });

    this.events.forEach(function (event) {
      var begins = parseMoment(event.startsAt);

      if (!begins) {
        return;
      }

      var ends = parseMoment(event.endsAt);
      var open = !ends;

      if (!ends || ends <= begins) {
        ends = new Date(begins.getTime() + 2 * step * MINUTE);
      }

      days.forEach(function (day) {
        var from = Math.max(begins.getTime(), day.getTime());
        var to = Math.min(ends.getTime(), day.getTime() + DAY);

        if (from < to || (from === to && from === begins.getTime())) {
          pieces[iso(day)].push({
            event: event,
            from: (from - day.getTime()) / MINUTE,
            to: (to - day.getTime()) / MINUTE,
            continued: begins.getTime() < day.getTime(),
            continues: ends.getTime() > day.getTime() + DAY,
            open: open,
            minutes: open ? 0 : (to - from) / MINUTE
          });
        }
      });
    });

    return pieces;
  };

  /** Pieces side by side where they overlap: a lane each. */
  function lanes(pieces) {
    var sorted = pieces.slice().sort(function (a, b) {
      return a.top - b.top || b.bottom - a.bottom;
    });
    var cluster = [];
    var ends = [];
    var reach = -1;

    function close() {
      cluster.forEach(function (piece) {
        piece.lanes = ends.length;
      });
      cluster = [];
      ends = [];
    }

    sorted.forEach(function (piece) {
      if (piece.top >= reach) {
        close();
      }

      var lane = 0;

      while (lane < ends.length && ends[lane] > piece.top) {
        lane += 1;
      }

      ends[lane] = piece.bottom;
      piece.lane = lane;
      cluster.push(piece);
      reach = Math.max(reach, piece.bottom);
    });
    close();

    return sorted;
  }

  CalendarView.prototype.drawHours = function () {
    var self = this;
    var shown = this.shown;
    var first = this.config.hours[0] * 60;
    var last = this.config.hours[1] * 60;
    var days = [];

    for (var day = shown.start; day < shown.end; day = addDays(day, 1)) {
      days.push(day);
    }

    var pieces = this.segments(days);
    var grid = el("div", "calendar-hours");
    var head = el("div", "calendar-hours__head");
    var body = el("div", "calendar-hours__body");
    var gutter = el("div", "calendar-hours__gutter");
    var now = parseMoment(this.config.now);

    this.window = { first: first, last: last };
    grid.style.setProperty("--calendar-days", String(days.length));
    grid.style.setProperty("--calendar-hours", String((last - first) / 60));
    head.appendChild(el("div", "calendar-hours__corner"));

    for (var hour = first; hour < last; hour += 60) {
      var mark = el("span", "calendar-hours__hour", clock(hour));

      mark.style.top = ((hour - first) / (last - first)) * 100 + "%";
      gutter.appendChild(mark);
    }

    body.appendChild(gutter);

    days.forEach(function (day) {
      var key = iso(day);
      var label = el("div", "calendar-hours__weekday");
      var total = 0;

      (pieces[key] || []).forEach(function (piece) {
        total += piece.minutes;
      });

      label.appendChild(el("span", "calendar-hours__name", format(day, { weekday: days.length > 1 ? "short" : "long" })));
      label.appendChild(el("span", "calendar-hours__date", format(day, { day: "numeric", month: "short" })));

      if (self.config.endField && total) {
        var sum = el("span", "calendar-hours__total", lasting(total));

        sum.title = t("Time on this day");
        label.appendChild(sum);
      }

      if (key === iso(self.today)) {
        label.classList.add("calendar-hours__weekday--today");
      }

      head.appendChild(label);
      body.appendChild(self.hoursColumn(day, pieces[key] || [], now));
    });

    grid.appendChild(head);
    grid.appendChild(body);
    grid.setAttribute("aria-label", shown.title);
    this.body.appendChild(grid);

    if (this.config.addUrl || this.config.moveUrl || this.config.allocate) {
      this.body.appendChild(el("p", "calendar-hours__hint muted", this.hint()));
    }
  };

  CalendarView.prototype.hint = function () {
    var parts = [];

    if (this.config.addUrl) {
      parts.push(t("Drag across the hours to add one."));
    }

    if (this.config.moveUrl) {
      parts.push(t("Drag a record to move it, its lower edge to change its end."));
    }

    if (this.config.allocate) {
      parts.push(t("Drop one of the list on a time to plan it."));
    }

    return parts.join(" ");
  };

  CalendarView.prototype.hoursColumn = function (day, pieces, now) {
    var self = this;
    var key = iso(day);
    var first = this.window.first;
    var last = this.window.last;
    var span = last - first;
    var step = this.config.step || 15;
    var column = el("div", "calendar-hours__day");

    column.setAttribute("data-day", key);
    column.setAttribute("aria-label", format(day, { weekday: "long", day: "numeric", month: "long" }));

    if (key === iso(this.today)) {
      column.classList.add("calendar-hours__day--today");
    }

    pieces.forEach(function (piece) {
      var top = Math.min(Math.max(piece.from, first), last);
      var bottom = Math.min(Math.max(piece.to, first), last);

      piece.clipped = top !== piece.from || bottom !== piece.to;

      if (bottom - top < step) {
        top = Math.min(top, last - step);
        bottom = top + step;
      }

      piece.top = top;
      piece.bottom = bottom;
    });

    lanes(pieces).forEach(function (piece) {
      var block = self.hoursEvent(piece, day);

      block.style.top = ((piece.top - first) / span) * 100 + "%";
      block.style.height = ((piece.bottom - piece.top) / span) * 100 + "%";
      block.style.left = (piece.lane / piece.lanes) * 100 + "%";
      block.style.width = (1 / piece.lanes) * 100 + "%";
      column.appendChild(block);
    });

    if (now && iso(now) === key) {
      var minutes = (now.getTime() - day.getTime()) / MINUTE;

      if (minutes >= first && minutes <= last) {
        var line = el("div", "calendar-hours__now");

        line.style.top = ((minutes - first) / span) * 100 + "%";
        line.setAttribute("aria-hidden", "true");
        column.appendChild(line);
      }
    }

    this.hoursTarget(column, day);
    this.hoursSelect(column, day);

    return column;
  };

  CalendarView.prototype.hoursEvent = function (piece, day) {
    var self = this;
    var event = piece.event;
    var colour = Generic.colors.clean(event.background) || Generic.colors.clean(event.color);
    var block = el("div", "calendar-event calendar-hours__event");
    var linked = event.url && Generic.isSafeUrl(event.url);
    var times = clock(piece.from) + "\u2013" + (piece.open ? "" : clock(piece.to));
    var label = linked ? values.link(event.url, event.label) : el("span", "", event.label);

    if (colour) {
      block.style.setProperty("--event-color", colour);
    }

    block.classList.toggle("calendar-event--continued", piece.continued);
    block.classList.toggle("calendar-event--continues", piece.continues);
    block.classList.toggle("calendar-hours__event--open", piece.open);
    block.classList.toggle("calendar-hours__event--short", piece.bottom - piece.top <= 2 * (this.config.step || 15));
    block.appendChild(el("span", "calendar-event__time", times));
    label.classList.add("calendar-event__label");
    block.appendChild(label);
    block.title = [times + (piece.open ? "" : " (" + lasting(piece.minutes) + ")"), event.label]
      .concat(
        (event.cells || []).map(function (entry) {
          return entry.empty ? "" : entry.label + ": " + (entry.display || (entry.items || []).map(function (item) {
            return item.label;
          }).join(", "));
        })
      )
      .filter(Boolean)
      .join("\n");

    if ((event.cells || []).length) {
      var cells = el("span", "calendar-event__cells");

      event.cells.forEach(function (entry) {
        if (!entry.empty) {
          cells.appendChild(values.render(entry));
        }
      });
      block.appendChild(cells);
    }

    if (!event.editable || !this.config.moveUrl) {
      return block;
    }

    block.draggable = true;
    // The record moves, not its link.
    label.setAttribute("draggable", "false");
    block.addEventListener("dragstart", function (dragEvent) {
      var box = block.getBoundingClientRect();
      var column = block.parentNode.getBoundingClientRect();
      var span = self.window.last - self.window.first;

      dragEvent.dataTransfer.effectAllowed = "move";
      dragEvent.dataTransfer.setData("text/plain", event.id);
      self.dragging = event;
      self.grab = {
        // Where the record was taken, in minutes below its start.
        offset: ((dragEvent.clientY - box.top) / column.height) * span + (piece.top - piece.from),
        length: piece.open ? 2 * (self.config.step || 15) : (parseMoment(event.endsAt) - parseMoment(event.startsAt)) / MINUTE
      };
      self.element.classList.add("is-dragging");
    });
    block.addEventListener("dragend", function () {
      self.dragging = null;
      self.grab = null;
      self.element.classList.remove("is-dragging");
      self.clearGhost();
    });

    if (this.config.endField && !piece.open && !piece.continues) {
      var handle = el("div", "calendar-hours__resize");

      handle.title = t("Drag to change its end");
      handle.setAttribute("aria-hidden", "true");
      block.appendChild(handle);
      this.hoursResize(block, handle, piece, day);
    }

    return block;
  };

  /** The minutes from midnight a pointer points at in a day's column,
   * snapped to the step. */
  CalendarView.prototype.minutesAt = function (column, clientY, offset) {
    var step = this.config.step || 15;
    var box = column.getBoundingClientRect();
    var span = this.window.last - this.window.first;
    var minutes = this.window.first + ((clientY - box.top) / box.height) * span - (offset || 0);

    minutes = Math.round(minutes / step) * step;

    return Math.min(Math.max(minutes, this.window.first), this.window.last - step);
  };

  CalendarView.prototype.ghost = function (column, from, to) {
    var span = this.window.last - this.window.first;
    var box = this.ghostBox;

    if (!box) {
      box = this.ghostBox = el("div", "calendar-hours__ghost");
      box.setAttribute("aria-hidden", "true");
    }

    if (box.parentNode !== column) {
      column.appendChild(box);
    }

    to = Math.min(to, this.window.last);
    box.style.top = ((from - this.window.first) / span) * 100 + "%";
    box.style.height = (Math.max(to - from, 1) / span) * 100 + "%";
    box.textContent = clock(from) + "\u2013" + clock(to);
  };

  CalendarView.prototype.clearGhost = function () {
    if (this.ghostBox && this.ghostBox.parentNode) {
      this.ghostBox.parentNode.removeChild(this.ghostBox);
    }
  };

  /** A day's hours take a record moved, or one of the panel's. */
  CalendarView.prototype.hoursTarget = function (column, day) {
    var self = this;

    function length() {
      return self.dragging ? self.grab.length : self.config.allocate.duration || 60;
    }

    function wanted() {
      return (self.dragging && self.config.moveUrl && self.grab) || (self.allocating && self.config.allocate);
    }

    column.addEventListener("dragover", function (event) {
      if (!wanted()) {
        return;
      }

      event.preventDefault();

      var from = self.minutesAt(column, event.clientY, self.dragging ? self.grab.offset : 0);

      self.ghost(column, from, from + length());
    });
    column.addEventListener("dragleave", function (event) {
      if (!column.contains(event.relatedTarget)) {
        self.clearGhost();
      }
    });
    column.addEventListener("drop", function (event) {
      if (!wanted()) {
        return;
      }

      event.preventDefault();
      self.clearGhost();

      var from = self.minutesAt(column, event.clientY, self.dragging ? self.grab.offset : 0);
      var start = moment(day, from);

      if (self.dragging) {
        self.moveTo(self.dragging, { start: start });
      } else {
        self.allocate(self.allocating, start, moment(day, from + length()));
      }
    });
  };

  /** Dragging a record's lower edge: another end. */
  CalendarView.prototype.hoursResize = function (block, handle, piece, day) {
    var self = this;
    var step = this.config.step || 15;
    var span = this.window.last - this.window.first;

    handle.addEventListener("pointerdown", function (down) {
      if (down.button !== 0) {
        return;
      }

      var column = block.parentNode;
      var end = piece.to;

      down.preventDefault();
      down.stopPropagation();
      block.draggable = false;
      block.classList.add("is-resizing");
      handle.setPointerCapture(down.pointerId);

      function follow(event) {
        var box = column.getBoundingClientRect();
        var minutes = self.window.first + ((event.clientY - box.top) / box.height) * span;

        end = Math.max(piece.from + step, Math.min(Math.round(minutes / step) * step, self.window.last));
        block.style.height = ((end - piece.top) / span) * 100 + "%";
        block.querySelector(".calendar-event__time").textContent = clock(piece.from) + "\u2013" + clock(end);
      }

      function stop() {
        handle.removeEventListener("pointermove", follow);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
        block.draggable = true;
        block.classList.remove("is-resizing");

        if (end !== piece.to) {
          self.moveTo(piece.event, { end: moment(day, end) });
        }
      }

      handle.addEventListener("pointermove", follow);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
  };

  /** Empty hours dragged across: the add form, start and end filled. */
  CalendarView.prototype.hoursSelect = function (column, day) {
    var self = this;
    var step = this.config.step || 15;

    if (!this.config.addUrl || !Generic.isSafeUrl(this.config.addUrl)) {
      return;
    }

    column.addEventListener("pointerdown", function (down) {
      if (down.button !== 0 || down.target !== column) {
        return;
      }

      var box = column.getBoundingClientRect();
      var span = self.window.last - self.window.first;
      var origin = self.window.first + ((down.clientY - box.top) / box.height) * span;
      var anchor = Math.floor(origin / step) * step;
      var range = null;

      down.preventDefault();
      column.setPointerCapture(down.pointerId);

      function follow(event) {
        var minutes = self.window.first + ((event.clientY - box.top) / box.height) * span;
        var from = Math.min(anchor, Math.floor(minutes / step) * step);
        var to = Math.max(anchor + step, Math.ceil(minutes / step) * step);

        from = Math.max(from, self.window.first);
        to = Math.min(to, self.window.last);

        if (Math.abs(minutes - origin) >= step / 2) {
          range = { from: from, to: to };
          self.ghost(column, from, to);
        }
      }

      function stop() {
        column.removeEventListener("pointermove", follow);
        column.removeEventListener("pointerup", stop);
        column.removeEventListener("pointercancel", stop);
        self.clearGhost();

        if (range) {
          self.openAdd(moment(day, range.from), moment(day, range.to));
        }
      }

      column.addEventListener("pointermove", follow);
      column.addEventListener("pointerup", stop);
      column.addEventListener("pointercancel", stop);
    });
  };

  /** The add form in a window of its own: the calendar stays, and
   * draws the record once the window says it was saved. */
  CalendarView.prototype.openAdd = function (start, end) {
    var url = new URL(this.config.addUrl, window.location.href);
    var request = "calendar-" + Date.now() + "-" + Math.random().toString(36).slice(2);

    url.searchParams.set(this.config.dateField, start);

    if (this.config.endField) {
      url.searchParams.set(this.config.endField, end);
    }

    url.searchParams.set("_popup", "1");
    url.searchParams.set("_relation_request", request);
    this.requests = this.requests || {};
    this.requests[request] = true;

    var width = 980;
    var height = 760;
    var opened = window.open(
      url.pathname + url.search,
      request,
      "popup=yes,width=" + width + ",height=" + height +
        ",left=" + Math.max(0, window.screenX + (window.outerWidth - width) / 2) +
        ",top=" + Math.max(0, window.screenY + (window.outerHeight - height) / 2) +
        ",resizable=yes,scrollbars=yes"
    );

    if (!opened) {
      // No window: the form itself, in this tab.
      url.searchParams.delete("_popup");
      url.searchParams.delete("_relation_request");
      window.location.assign(url.pathname + url.search);
      return;
    }

    opened.focus();
  };

  CalendarView.prototype.saved = function (event) {
    var data = event.data || {};

    if (event.origin !== window.location.origin || data.type !== SAVED_MESSAGE || !this.requests || !this.requests[data.requestId]) {
      return;
    }

    delete this.requests[data.requestId];
    Generic.toast(Generic.format(t("\u201c%(name)s\u201d was saved."), { name: data.label || String(data.id) }), "success");
    this.refresh();
  };

  /** Another start or end, on the hours. */
  CalendarView.prototype.moveTo = function (event, change) {
    var self = this;

    if (change.start && change.start === event.startsAt) {
      return;
    }

    var url = this.config.moveUrl.replace("{id}", encodeURIComponent(event.id));

    Generic.api
      .patch(url, change)
      .then(function () {
        Generic.toast(Generic.format(change.start ? t("%(label)s moved.") : t("%(label)s changed."), { label: event.label }), "success");
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The record could not be moved."), "error");
      })
      .then(function () {
        self.refresh();
      });
  };

  /* -- What may be dropped on it --------------------------------------- */

  CalendarView.prototype.buildPanel = function () {
    var self = this;
    var allocate = this.config.allocate;
    var panel = el("aside", "calendar-allocate");
    var title = el("h3", "calendar-allocate__title", allocate.title);
    var search = el("input", "input input--sm calendar-allocate__search");
    var list = el("ul", "calendar-allocate__items");
    var more = el("button", "button button--sm button--ghost calendar-allocate__more", t("Show more"));

    panel.setAttribute("aria-label", allocate.title);
    search.type = "search";
    search.placeholder = t("Search");
    search.setAttribute("aria-label", Generic.format(t("Search %(name)s"), { name: allocate.title }));
    more.type = "button";
    more.hidden = true;
    panel.appendChild(title);
    panel.appendChild(el("p", "calendar-allocate__hint muted", t("Drag one onto the calendar.")));
    panel.appendChild(search);
    panel.appendChild(list);
    panel.appendChild(more);
    this.sources = { list: list, more: more, page: 1, term: "" };

    search.addEventListener(
      "input",
      Generic.debounce(function () {
        self.sources.term = search.value.trim();
        self.loadSources(1);
      }, 250)
    );
    more.addEventListener("click", function () {
      self.loadSources(self.sources.page + 1);
    });

    return panel;
  };

  CalendarView.prototype.loadSources = function (page) {
    var self = this;
    var sources = this.sources;
    var asked = {};

    sources.asking = asked;

    return Generic.api
      .get(this.config.allocate.url, { q: sources.term, page: page })
      .then(function (answer) {
        if (sources.asking !== asked) {
          return;
        }

        if (page === 1) {
          sources.list.textContent = "";
        }

        (answer.items || []).forEach(function (item) {
          sources.list.appendChild(self.sourceItem(item));
        });

        if (page === 1 && !(answer.items || []).length) {
          sources.list.appendChild(el("li", "calendar-allocate__empty muted", t("Nothing to offer.")));
        }

        sources.page = page;
        sources.more.hidden = !answer.more;
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The list could not be loaded."), "error");
      });
  };

  CalendarView.prototype.sourceItem = function (item) {
    var self = this;
    var entry = el("li", "calendar-event calendar-allocate__item");
    var colour = Generic.colors.clean(item.background) || Generic.colors.clean(item.color);
    var label = item.url && Generic.isSafeUrl(item.url) ? values.link(item.url, item.label) : el("span", "", item.label);

    if (colour) {
      entry.style.setProperty("--event-color", colour);
    }

    entry.appendChild(icon("drag_indicator"));
    label.classList.add("calendar-event__label");
    entry.appendChild(label);

    if ((item.cells || []).length) {
      var cells = el("span", "calendar-event__cells");

      item.cells.forEach(function (cell) {
        if (!cell.empty) {
          cells.appendChild(values.render(cell));
        }
      });
      entry.appendChild(cells);
    }

    entry.draggable = true;
    entry.title = item.label;
    entry.addEventListener("dragstart", function (event) {
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("text/plain", item.label);
      self.allocating = item;
      self.element.classList.add("is-dragging");
    });
    entry.addEventListener("dragend", function () {
      self.allocating = null;
      self.element.classList.remove("is-dragging");
      self.clearGhost();
    });

    return entry;
  };

  /** A record created on a time (or a day), pointing at ``item``. */
  CalendarView.prototype.allocate = function (item, start, end) {
    var self = this;
    var body = { record: item.id, start: start };

    if (end) {
      body.end = end;
    }

    Generic.api
      .post(this.config.allocate.createUrl, body)
      .then(function () {
        Generic.toast(Generic.format(t("%(label)s planned."), { label: item.label }), "success");
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The record could not be created."), "error");
      })
      .then(function () {
        self.refresh();
      });
  };

  /* -- Following the table and the records --------------------------------- */

  /** Follow a table's filters and search box (the resource's own
   * table, its rows hidden): the calendar shows the records it would
   * list. */
  CalendarView.prototype.linkTable = function (id) {
    var self = this;
    var table = id ? document.querySelector('table[data-config="' + window.CSS.escape(id) + '"]') : null;

    if (!table) {
      this.refresh();
      return;
    }

    function link(controller) {
      var last = null;
      var follow = Generic.debounce(function () {
        var params = controller.currentParams();
        var wanted = { filters: params.filters || "", search: params.search || "" };
        var key = JSON.stringify(wanted);

        if (key !== last) {
          last = key;
          self.tableFilters = wanted;
          self.refresh();
        }
      }, 150);

      controller.instance.on("xhr.dt", follow);
    }

    if (table.genericDataTable && table.genericDataTable.instance) {
      link(table.genericDataTable);
      return;
    }

    table.addEventListener(
      "generic:datatable-ready",
      function (event) {
        link(event.detail.controller);
      },
      { once: true }
    );

    var tables = window.GenericDataTables;

    if (tables && typeof tables.start === "function") {
      tables.start(table);
    } else {
      document.addEventListener(
        "generic:datatables-loaded",
        function () {
          window.GenericDataTables.start(table);
        },
        { once: true }
      );
    }
  };

  /** Load again when a record of the resource changes. */
  CalendarView.prototype.follow = function () {
    var self = this;

    if (!Generic.events || !(this.config.topics || []).length) {
      return;
    }

    var reload = Generic.debounce(function () {
      self.refresh();
    }, 600);

    this.config.topics.forEach(function (topic) {
      Generic.events.subscribe(topic);
    });
    Generic.events.on("resource.changed", function (payload) {
      if (payload && payload.resource && payload.resource !== self.config.resource) {
        return;
      }

      if (document.body.contains(self.element)) {
        reload();
      }
    });
  };

  CalendarView.prototype.start = function () {
    this.linkTable(this.config.filterTable);
    this.follow();

    if (this.panel) {
      this.loadSources(1);
    }
  };

  function start(element) {
    if (!element || element.genericCalendar) {
      return element && element.genericCalendar;
    }

    var config = readJson(element.getAttribute("data-config"));

    if (!config || !config.url) {
      return null;
    }

    var view = new CalendarView(element, config);

    element.genericCalendar = view;
    view.start();

    return view;
  }

  Generic.calendar = { start: start };

  Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".generic-calendar[data-autostart]"), start);
  });
})(window, document);

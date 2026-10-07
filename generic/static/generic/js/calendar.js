/**
 * Records on a calendar (generic.sites.calendars): a month, a week, or
 * the days of a month as a list.
 *
 * The page asks the calendar's endpoint for the days it shows, and
 * again when they change, when the table above it is filtered or
 * searched, or when a record of the resource changes. With moveUrl, a
 * record dragged onto another day is written there.
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
  var VIEW_ICONS = { month: "calendar_view_month", week: "calendar_view_week", list: "view_agenda" };
  var VIEW_LABELS = { month: t("Month"), week: t("Week"), list: t("List") };

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
    this.element.appendChild(this.body);
  };

  /** The days shown: [start, end), and the heading saying which. */
  CalendarView.prototype.range = function () {
    var first = this.config.firstDay || 0;

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

    if (this.view === "list") {
      this.drawList();
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

    if (!this.config.moveUrl) {
      return;
    }

    cell.addEventListener("dragover", function (event) {
      if (self.dragging) {
        event.preventDefault();
        cell.classList.add("is-over");
      }
    });
    cell.addEventListener("dragleave", function () {
      cell.classList.remove("is-over");
    });
    cell.addEventListener("drop", function (event) {
      cell.classList.remove("is-over");

      if (!self.dragging) {
        return;
      }

      event.preventDefault();
      self.move(self.dragging, key);
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
    var week = this.view === "week";
    var grid = el("div", "calendar-grid" + (week ? " calendar-grid--week" : ""));
    var head = el("div", "calendar-grid__head");

    for (var index = 0; index < 7; index += 1) {
      var weekday = addDays(shown.start, index);

      head.appendChild(el("div", "calendar-grid__weekday", format(weekday, { weekday: week ? "long" : "short" })));
    }

    grid.appendChild(head);

    var body = el("div", "calendar-grid__days");

    for (var day = shown.start; day < shown.end; day = addDays(day, 1)) {
      body.appendChild(this.dayCell(day, days[iso(day)] || [], week));
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

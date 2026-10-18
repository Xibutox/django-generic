/**
 * Records on a board (generic.sites.boards): a column per value of a
 * field, a card per record.
 *
 * The page asks the board's endpoint for its columns, and again when
 * the table above it is filtered or searched, or when a record of the
 * resource changes. With moveUrl, a card dragged onto another column -
 * or sent there from its "Move to" menu, by keyboard - is written there.
 *
 *   <div class="generic-board" data-config="<id of a json_script>"></div>
 *   Generic.board.start(element)
 *
 * Every value reaches the page through textContent, every address
 * through Generic.isSafeUrl, every colour through Generic.colors.clean.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var values = Generic.values;
  var el = values.el;
  var icon = values.icon;

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

  /** A column's key as text: the same for 3 and "3", null apart. */
  function keyText(key) {
    return key === null || key === undefined ? "\u0000" : String(key);
  }

  function BoardView(element, config) {
    this.element = element;
    this.config = config;
    this.tableFilters = { filters: "", search: "" };
    this.columns = [];
    this.asking = null;
    this.dragging = null;
    this.build();
  }

  BoardView.prototype.build = function () {
    var toolbar = el("div", "board__toolbar");

    this.status = el("span", "board__status muted");
    this.status.setAttribute("aria-live", "polite");
    toolbar.appendChild(this.status);

    this.body = el("div", "board__columns");
    this.element.textContent = "";
    this.element.appendChild(toolbar);
    this.element.appendChild(this.body);
  };

  BoardView.prototype.refresh = function () {
    var self = this;
    var params = {};
    var asked = {};

    if (this.tableFilters.filters) {
      params.filters = this.tableFilters.filters;
    }

    if (this.tableFilters.search) {
      params.search = this.tableFilters.search;
    }

    this.status.textContent = t("Loading\u2026");
    this.asking = asked;

    return Generic.api
      .get(this.config.url, params)
      .then(function (answer) {
        // Asked again meanwhile: that answer draws instead.
        if (self.asking !== asked) {
          return;
        }

        self.columns = answer.columns || [];
        self.draw();

        var count = self.columns.reduce(function (total, column) {
          return total + (column.count || 0);
        }, 0);

        self.status.textContent = count
          ? Generic.format(Generic.nt("%(count)s record", "%(count)s records", count), { count: count })
          : t("Nothing to show.");
      })
      .catch(function (error) {
        if (self.asking === asked) {
          self.status.textContent = "";
          Generic.toast((error && error.message) || t("The board could not be loaded."), "error");
        }
      });
  };

  BoardView.prototype.draw = function () {
    var self = this;

    this.body.textContent = "";
    this.columns.forEach(function (column) {
      self.body.appendChild(self.drawColumn(column));
    });
  };

  /* -- A column ------------------------------------------------------- */

  BoardView.prototype.drawColumn = function (column) {
    var self = this;
    var section = el("section", "board-column");
    var header = el("header", "board-column__head");
    var title = el("h2", "board-column__title");
    var colour = Generic.colors.clean(column.background) || Generic.colors.clean(column.color);
    var list = el("div", "board-column__cards");
    var headingId = "board-column-" + this.config.name + "-" + this.columns.indexOf(column);

    section.setAttribute("data-column", keyText(column.key));
    section.setAttribute("aria-labelledby", headingId);

    if (colour) {
      section.style.setProperty("--column-color", colour);
    }

    title.id = headingId;
    title.appendChild(el("span", "board-column__label", column.label));
    title.appendChild(el("span", "board-column__count", String(column.count || 0)));
    header.appendChild(title);

    var add = this.addLink(column);

    if (add) {
      header.appendChild(add);
    }

    section.appendChild(header);

    (column.cards || []).forEach(function (card) {
      list.appendChild(self.drawCard(card, column));
    });

    if (!(column.cards || []).length) {
      list.appendChild(el("p", "board-column__empty muted", t("No record here.")));
    }

    if (column.truncated) {
      list.appendChild(
        el(
          "p",
          "board-column__more muted",
          Generic.format(t("The first %(count)s only: filter the table."), { count: this.config.maxCards })
        )
      );
    }

    section.appendChild(list);
    this.dropTarget(section, column);

    return section;
  };

  BoardView.prototype.addLink = function (column) {
    if (!this.config.addUrl || !Generic.isSafeUrl(this.config.addUrl) || column.key === null) {
      return null;
    }

    var link = el("a", "board-column__add icon-button icon-button--sm");
    var label = Generic.format(t("Add to %(column)s"), { column: column.label });
    var url = new URL(this.config.addUrl, window.location.href);

    url.searchParams.set(this.config.field, String(column.key));
    link.href = url.pathname + url.search;
    link.title = label;
    link.setAttribute("aria-label", label);
    link.appendChild(icon("add"));

    return link;
  };

  /** A column accepts a dragged card. */
  BoardView.prototype.dropTarget = function (section, column) {
    var self = this;

    if (!this.config.moveUrl) {
      return;
    }

    section.addEventListener("dragover", function (event) {
      if (self.dragging) {
        event.preventDefault();
        section.classList.add("is-over");
      }
    });
    section.addEventListener("dragleave", function (event) {
      if (!section.contains(event.relatedTarget)) {
        section.classList.remove("is-over");
      }
    });
    section.addEventListener("drop", function (event) {
      section.classList.remove("is-over");

      if (!self.dragging) {
        return;
      }

      event.preventDefault();
      self.move(self.dragging, column);
    });
  };

  /* -- A card --------------------------------------------------------- */

  BoardView.prototype.drawCard = function (card, column) {
    var self = this;
    var element = el("article", "board-card-item");
    var colour = Generic.colors.clean(card.background) || Generic.colors.clean(card.color);
    var label = values.link(card.url, card.label);

    element.setAttribute("data-id", card.id);

    if (colour) {
      element.style.setProperty("--card-color", colour);
    }

    label.classList.add("board-card-item__label");
    element.appendChild(label);

    var cells = (card.cells || []).filter(function (entry) {
      return !entry.empty;
    });

    if (cells.length) {
      var list = el("div", "board-card-item__cells");

      cells.forEach(function (entry) {
        var row = el("div", "board-card-item__cell");
        var name = el("span", "board-card-item__name", entry.label);

        row.appendChild(name);
        row.appendChild(values.render(entry));
        list.appendChild(row);
      });
      element.appendChild(list);
    }

    if (card.editable && this.config.moveUrl) {
      element.draggable = true;
      element.addEventListener("dragstart", function (event) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.id);
        self.dragging = card;
        self.element.classList.add("is-dragging");
      });
      element.addEventListener("dragend", function () {
        self.dragging = null;
        self.element.classList.remove("is-dragging");
      });
      element.appendChild(this.moveMenu(card, column));
    }

    return element;
  };

  /** "Move to": the same move as a drag, for a keyboard or a screen
   * reader. */
  BoardView.prototype.moveMenu = function (card, column) {
    var self = this;
    var select = el("select", "board-card-item__move input input--sm");
    var placeholder = el("option", "", t("Move to\u2026"));

    placeholder.value = "";
    select.appendChild(placeholder);
    select.setAttribute("aria-label", Generic.format(t("Move %(label)s to"), { label: card.label }));

    this.columns.forEach(function (other, index) {
      if (keyText(other.key) === keyText(column.key)) {
        return;
      }

      var option = el("option", "", other.label);

      option.value = String(index);
      select.appendChild(option);
    });

    select.addEventListener("change", function () {
      var target = self.columns[Number(select.value)];

      if (select.value !== "" && target) {
        self.move(card, target);
      }
    });

    return select;
  };

  BoardView.prototype.move = function (card, column) {
    var self = this;

    if (keyText(card.column) === keyText(column.key)) {
      return;
    }

    var url = this.config.moveUrl.replace("{id}", encodeURIComponent(card.id));

    Generic.api
      .patch(url, { column: column.key })
      .then(function () {
        Generic.toast(Generic.format(t("%(label)s moved to %(column)s."), { label: card.label, column: column.label }), "success");
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The record could not be moved."), "error");
      })
      .then(function () {
        self.refresh();
      });
  };

  /* -- Following the table and the records ----------------------------- */

  /** Follow a table's filters and search box (the resource's own table,
   * its rows hidden): the board shows the records it would list. */
  BoardView.prototype.linkTable = function (id) {
    var self = this;
    var table = id ? document.querySelector('table[data-config="' + window.CSS.escape(id) + '"]') : null;

    // Drawn now, not once the table has loaded: its first answer, with
    // no filter, changes nothing and would draw the board twice.
    this.refresh();

    if (!table) {
      return;
    }

    function link(controller) {
      var last = JSON.stringify(self.tableFilters);
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
  BoardView.prototype.follow = function () {
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

  BoardView.prototype.start = function () {
    this.linkTable(this.config.filterTable);
    this.follow();
  };

  function start(element) {
    if (!element || element.genericBoard) {
      return element && element.genericBoard;
    }

    var config = readJson(element.getAttribute("data-config"));

    if (!config || !config.url) {
      return null;
    }

    var view = new BoardView(element, config);

    element.genericBoard = view;
    view.start();

    return view;
  }

  Generic.board = { start: start };

  Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".generic-board[data-autostart]"), start);
  });
})(window, document);

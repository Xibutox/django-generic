/**
 * A list unfolding into its related records, edited where they stand
 * (generic.sites.outlines).
 *
 * The table's toolbar gets an "Outline" button. Pressed, the rows make
 * way for a tree drawn like the tree pages (css/tree.css): the table's
 * records first - its filters, search and order still apply - each
 * with an arrow to the records of the next level, which have one to
 * theirs. A level may unfold into several relations: each is drawn
 * below the record in the order declared, its own heading, pages and
 * foot. Nothing is fetched before it is unfolded: a relation is one
 * request, a page at a time.
 *
 * Each level is drawn with its own resource's columns and the same
 * renderers as its table (columns.js). The cells its resource lets
 * this reader write are their controls - the form's widgets - and are
 * written as a grid writes them: one PATCH .../<pk>/cells/ a cell, the
 * answer the whole row (editable.js).
 *
 * Every value reaches the page through textContent or a renderer that
 * escapes it, every address through isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var columnsModule = namespace.columns;
  var t = core.t;
  var el = core.el;

  //: How long a change this page made itself is recognised when the
  //: socket reports it back.
  var OWN_WRITE_MS = 5000;
  //: The address parameter opening the list as its outline.
  var URL_PARAM = "outline";
  //: The records one request unfolds at once (outlines.MAX_PARENTS).
  var PARENTS_AT_ONCE = 25;
  //: The records one press of *Expand next level* unfolds: a level
  //: holding more takes another press.
  var UNFOLD_AT_ONCE = 50;

  function generic() {
    return window.Generic;
  }

  function widgets() {
    var Generic = generic();

    return Generic && Generic.forms && Generic.forms.widgets;
  }

  function cells() {
    return namespace.cells;
  }

  function icon(name, extra) {
    return core.icon(name, "icon--sm" + (extra ? " " + extra : ""));
  }

  function number(value) {
    try {
      return Number(value).toLocaleString(document.documentElement.lang || undefined);
    } catch (error) {
      return String(value);
    }
  }

  /** Every other record's row shaded, as a table's are: counted down
   * the page, whatever level each is at. */
  function stripe(body) {
    var shaded = false;

    Array.prototype.forEach.call(
      body.querySelectorAll("tr.tree-row:not(.tree-row--foot):not(.tree-row--head)"),
      function (row) {
        row.classList.toggle("is-stripe", shaded);
        shaded = !shaded;
      }
    );
  }

  /** A CSS colour, and nothing else: what the server sends, checked
   * again before it is written into a style. */
  var COLOR = /^(#[0-9a-f]{3,8}|[a-z]{3,30}|(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\([0-9a-z .,%\/+-]{1,80}\))$/i;

  /** A level's rows marked with its colour (`level.color`): the records
   * of one model told from another's at a glance. */
  function tint(row, level) {
    var color = level && level.color;

    if (color && COLOR.test(String(color))) {
      row.classList.add("has-tint");
      row.style.setProperty("--outline-tint", String(color));
    }

    return row;
  }

  function focusWithin(node) {
    return Boolean(node && node.contains(document.activeElement));
  }

  function storageKey(controller) {
    return "generic.outline." + (controller.options.stateKey || controller.url);
  }

  /** Whether the table owns the page's address: a related table on a
   * record's page shares it with others, and keeps its choice to itself. */
  function ownsAddress(controller) {
    return controller.options.syncUrl !== false;
  }

  function remembered(controller) {
    try {
      if (
        ownsAddress(controller) &&
        new URLSearchParams(window.location.search).get(URL_PARAM) === "1"
      ) {
        return true;
      }

      return window.localStorage.getItem(storageKey(controller)) === "1";
    } catch (error) {
      return false;
    }
  }

  function editKey(controller) {
    return "generic.outline-edit." + (controller.options.stateKey || controller.url);
  }

  /** Edited from the start: the page is the list's grid (?edit=1), or
   * the reader left the outline being edited. */
  function editingFirst(controller) {
    var toggle = controller.options.editToggle;

    if (toggle && toggle.active) {
      return true;
    }

    try {
      return window.localStorage.getItem(editKey(controller)) === "1";
    } catch (error) {
      return false;
    }
  }

  function remember(controller, active) {
    try {
      window.localStorage.setItem(storageKey(controller), active ? "1" : "0");
    } catch (error) {
      /* Private mode: the choice simply is not remembered. */
    }

    if (!ownsAddress(controller) || !window.history || !window.history.replaceState) {
      return;
    }

    var url = new URL(window.location.href);

    if (active) {
      url.searchParams.set(URL_PARAM, "1");
    } else {
      url.searchParams.delete(URL_PARAM);
    }

    if (url.toString() !== window.location.href) {
      window.history.replaceState(window.history.state, "", url.toString());
    }
  }

  /* -- A level, as its table describes it -------------------------------- */

  function Level(config, index) {
    // The number the endpoint knows it by; the levels below, by theirs
    // (linked by OutlineView: `children`).
    this.index = typeof config.index === "number" ? config.index : index;
    this.childIndexes = Array.isArray(config.children) ? config.children : null;
    this.children = [];
    this.name = config.name;
    this.resource = config.resource;
    this.title = config.title || "";
    this.label = config.label || "";
    this.columns = columnsModule.normalizeColumns(config.columns || []);
    this.editable = config.editable || {};
    this.editableUrl = config.editableUrl || "";
    this.addUrl = config.addUrl || "";
    // The add form in a dialog over the outline (add_in_dialog).
    this.addInDialog = Boolean(config.addInDialog);
    this.rowKey = config.rowKey || "_pk";
    // Opened in a dialog while editing - or always, the level opting
    // in (open_in_dialog) - and dragged into another order.
    this.changeUrl = config.changeUrl || "";
    this.openInDialog = Boolean(config.openInDialog);
    this.movable = Boolean(config.movable);
    // Its rows' colour, told from the other models' (tint()).
    this.color = config.color || "";
  }

  Level.prototype.writes = function (column) {
    return Boolean(this.editableUrl && column.data && this.editable[column.data]);
  };

  /* -- The outline -------------------------------------------------------- */

  function OutlineView(controller, config) {
    var self = this;
    var byIndex = {};

    this.controller = controller;
    this.config = config;
    this.pageSize = config.pageSize || 25;
    this.levels = (config.levels || []).map(function (level, index) {
      var made = new Level(level, index);

      byIndex[made.index] = made;

      return made;
    });
    // Each level's relations, in the order declared; a configuration
    // naming none is a chain, each level below the one before.
    this.levels.forEach(function (level, position) {
      var below = level.childIndexes || (position + 1 < self.levels.length ? [self.levels[position + 1].index] : []);

      level.children = below
        .map(function (index) {
          return byIndex[index];
        })
        .filter(Boolean);
    });
    this.width = Math.max.apply(
      null,
      this.levels.map(function (level) {
        return Math.max(1, level.columns.length);
      })
    );
    // Above the first level: the table, unfolding into its rows.
    this.top = this.node({ id: null }, -1, { children: this.levels.slice(0, 1), index: -1 });
    this.top.expanded = true;
    this.topSection = this.sectionsOf(this.top)[0];
    this.recentWrites = {};
    this.editable = this.levels.some(function (level) {
      return (
        (Object.keys(level.editable).length > 0 && Boolean(level.editableUrl) && Boolean(widgets())) ||
        level.movable ||
        Boolean(level.changeUrl && generic().dialogs)
      );
    });
    this.dragging = null;
    this.editing = false;
    this.active = false;
    this.asked = "";
    this.build();
  }

  /** A record of `level`, drawn `depth` steps below the top. Its
   * records below are in `sections`, one a relation of its level. */
  OutlineView.prototype.node = function (data, depth, level) {
    var relations = (level && level.children.length) || 0;
    var counts = Array.isArray(data.counts) ? data.counts.slice(0, relations) : [data.children || 0];

    return {
      id: data.id,
      url: data.url || "",
      row: data.row || {},
      level: level,
      counts: counts,
      count: counts.reduce(function (sum, value) {
        return sum + (Number(value) || 0);
      }, 0),
      depth: depth,
      expanded: false,
      sections: null,
      parent: null,
      element: null,
      cells: []
    };
  };

  /** The records of one relation below `owner`: what is loaded, paged,
   * headed and closed by a foot of its own. */
  function Section(owner, level, count) {
    this.owner = owner;
    this.level = level;
    this.count = Number(count) || 0;
    this.items = [];
    this.total = 0;
    this.loaded = false;
    this.loading = false;
    this.failed = false;
    this.asking = null;
    this.head = null;
  }

  /** The relations `node` unfolds into, in the order declared. */
  OutlineView.prototype.sectionsOf = function (node) {
    if (!node.sections) {
      node.sections = (node.level ? node.level.children : []).map(function (level, place) {
        return new Section(node, level, node.counts[place]);
      });
    }

    return node.sections;
  };

  /** The relations drawn below `node` when it is open: those holding
   * records, being read, or offering to add the first one. */
  OutlineView.prototype.shownSections = function (node) {
    var self = this;

    return this.sectionsOf(node).filter(function (section) {
      return (
        section.count > 0 ||
        section.total > 0 ||
        section.items.length > 0 ||
        section.loading ||
        section.failed ||
        Boolean(self.addUrlBelow(section))
      );
    });
  };

  OutlineView.prototype.loadingOf = function (node) {
    return (node.sections || []).some(function (section) {
      return section.loading;
    });
  };

  /** What a level unfolds into, as its heading names it. */
  function titlesBelow(level) {
    return (level ? level.children : [])
      .map(function (child) {
        return child.title || child.label;
      })
      .join(", ");
  }

  OutlineView.prototype.build = function () {
    var self = this;
    var root = el("div", "generic-tree dt-outline");
    var toolbar = el("div", "tree__toolbar");
    var status = el("span", "tree__status muted");
    var expand = el("button", "button button--sm button--ghost dt-outline-expand");
    var collapse = el("button", "button button--sm button--ghost");
    var refresh = el("button", "button button--sm button--ghost");

    expand.type = "button";
    expand.addEventListener("click", function () {
      self.expandLevel();
    });
    this.expandButton = expand;

    collapse.type = "button";
    collapse.append(icon("unfold_less"), el("span", "", t("Collapse all")));
    collapse.addEventListener("click", function () {
      self.collapseAll();
    });

    refresh.type = "button";
    refresh.append(icon("refresh"), el("span", "", t("Refresh")));
    refresh.addEventListener("click", function () {
      self.reload();
    });

    toolbar.append(status);

    // Read, until its reader asks to correct something: then every cell
    // its resource lets them write is its control.
    if (this.editable) {
      var edit = el("button", "button button--sm button--ghost dt-outline-edit");

      edit.type = "button";
      edit.addEventListener("click", function () {
        self.setEditing(!self.editing);

        try {
          window.localStorage.setItem(editKey(self.controller), self.editing ? "1" : "0");
        } catch (error) {
          /* Not remembered. */
        }
      });
      toolbar.appendChild(edit);
      this.editButton = edit;
      this.drawEditButton();
    }

    toolbar.append(expand, collapse, refresh);

    var scroller = el("div", "tree__scroll");
    var table = el("table", "tree-table outline-table");
    var head = el("thead");
    var headRow = el("tr");
    var top = this.levels[0];

    table.setAttribute("role", "treegrid");
    table.setAttribute("aria-label", this.config.title || t("Outline"));

    for (var index = 0; index < this.width; index += 1) {
      var column = top.columns[index];
      var th = el("th", index === 0 ? "tree-table__label" : "", column ? column.title : "");

      if (column && this.isNumber(column)) {
        th.classList.add("tree-row__number");
      }

      headRow.appendChild(th);
    }

    headRow.appendChild(el("th", "tree-table__tools"));
    head.appendChild(headRow);

    this.body = el("tbody");
    this.body.addEventListener("keydown", function (event) {
      self.keydown(event);
    });
    // Editing, or a level opening in a dialog: a record's link opens
    // its form over the outline.
    this.body.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a.tree-row__name, a.outline-row__open");
      var row = link && link.closest("tr.outline-row");

      if (row && row.outlineNode && self.opensInDialog(row.outlineNode)) {
        event.preventDefault();
        self.openRecord(row.outlineNode);
      }
    });
    this.bindDragging();

    table.append(head, this.body);
    scroller.appendChild(table);
    root.append(toolbar, scroller);
    root.hidden = true;

    this.root = root;
    this.status = status;
    this.drawExpandButton();
  };

  OutlineView.prototype.drawEditButton = function () {
    var button = this.editButton;

    if (!button) {
      return;
    }

    button.textContent = "";
    button.append(
      icon(this.editing ? "edit_off" : "edit"),
      el("span", "", this.editing ? t("Stop editing") : t("Edit"))
    );
    button.classList.toggle("is-active", this.editing);
    button.setAttribute("aria-pressed", String(this.editing));
    button.title = this.editing ? t("Back to reading the rows") : t("Edit the rows in place");
  };

  /** Every writable cell drawn as its control, or back to its value. */
  OutlineView.prototype.setEditing = function (on) {
    var self = this;

    this.editing = Boolean(on) && this.editable;
    this.drawEditButton();
    this.root.classList.toggle("is-editing", this.editing);

    this.walk(function (node) {
      self.drawOpenLink(node);
      node.cells.forEach(function (cell) {
        if (!cell.writable) {
          return;
        }

        if (!self.editing && cell.widget) {
          self.unmountCell(cell);
        }
      });
    });

    if (this.editing) {
      this.mountPending();
    }
  };

  /** Every record drawn or kept, top first, each before those below. */
  OutlineView.prototype.walk = function (visit) {
    (function down(node) {
      (node.sections || []).forEach(function (section) {
        section.items.forEach(function (child) {
          visit(child);
          down(child);
        });
      });
    })(this.top);
  };

  OutlineView.prototype.isNumber = function (column) {
    return column.filterType === "integer" || column.filterType === "float";
  };

  /* -- Showing it, in place of the rows ----------------------------------- */

  OutlineView.prototype.place = function () {
    var container = this.controller.instance.table().container();
    var rows = container.querySelector(".dt-layout-table");

    this.container = container;

    if (rows && rows.parentNode) {
      rows.parentNode.insertBefore(this.root, rows);
    } else {
      container.appendChild(this.root);
    }
  };

  OutlineView.prototype.show = function (active) {
    this.active = Boolean(active);
    this.root.hidden = !this.active;
    this.container.classList.toggle("is-outline", this.active);

    if (this.button) {
      this.button.classList.toggle("is-active", this.active);
      this.button.setAttribute("aria-pressed", String(this.active));
      this.button.title = this.active ? t("Back to the table") : t("Show the rows as an outline");
    }

    if (this.active) {
      this.follow();
    }
  };

  /** What the table selects now: the outline's first level follows it. */
  OutlineView.prototype.tableParams = function () {
    var controller = this.controller;
    var params = controller.currentParams();
    var order = controller.instance ? controller.instance.order() : [];
    var ordering = [];

    (order || []).forEach(function (entry) {
      var column = controller.columns[entry[0]];

      if (column && column.data && !column.synthetic) {
        ordering.push((entry[1] === "desc" ? "-" : "") + column.data);
      }
    });

    if (ordering.length) {
      params.ordering = ordering.join(",");
    }

    return params;
  };

  /** Load the first level again when the table's selection changed. */
  OutlineView.prototype.follow = function () {
    if (!this.active) {
      return;
    }

    var params = this.tableParams();
    var key = JSON.stringify(params);

    if (key === this.asked && this.topSection.loaded) {
      return;
    }

    this.asked = key;
    this.load(this.topSection, false);
  };

  /* -- Fetching ----------------------------------------------------------- */

  /** One page of `section`: the table's rows, or a record's. */
  OutlineView.prototype.fetch = function (section, offset, limit) {
    var params = { level: section.level.index, offset: offset, limit: limit || this.pageSize };

    if (section.owner === this.top) {
      Object.assign(params, this.tableParams());
    } else {
      // What the table always sends - a record's tab names its
      // relation - then the record unfolded.
      Object.assign(
        params,
        core.resolveExtraParams(this.controller.options, this.controller.table)
      );
      params.parent = section.owner.id;
    }

    return generic().api.get(this.config.url, params);
  };

  OutlineView.prototype.adopt = function (section, data, before) {
    var child = this.node(data, section.owner.depth + 1, section.level);

    child.parent = section;

    // Found again: it stays open, its relations' rows kept.
    if (before && before.expanded && this.opens(child)) {
      child.expanded = true;
      child.sections = before.sections;
      (child.sections || []).forEach(function (kept, place) {
        kept.owner = child;
        kept.count = Number(child.counts[place]) || 0;
      });
      before.sections = null;
    }

    if (before) {
      this.forget(before, false);
    }

    return child;
  };

  /** Fill `section` with the page asked for: replaced, or added to. */
  OutlineView.prototype.load = function (section, append, limit) {
    var self = this;
    var offset = append ? section.items.length : 0;
    var asking = {};

    section.asking = asking;
    section.loading = true;
    section.failed = false;
    this.redraw(section.owner);

    return this.fetch(section, offset, limit)
      .then(function (answer) {
        if (section.asking !== asking) {
          return;
        }

        var known = {};

        if (!append) {
          section.items.forEach(function (child) {
            known[child.id] = child;
          });
          section.items = [];
        }

        (answer.items || []).forEach(function (data) {
          section.items.push(self.adopt(section, data, known[data.id]));
          delete known[data.id];
        });

        Object.keys(known).forEach(function (key) {
          self.forget(known[key], true);
        });

        section.total = answer.total || 0;
        section.loaded = true;
        section.loading = false;

        if (section.owner === self.top) {
          self.announce();
        }

        self.redraw(section.owner);
      })
      .catch(function (error) {
        if (section.asking !== asking) {
          return;
        }

        section.loading = false;
        section.failed = true;
        self.redraw(section.owner);
        generic().toast((error && error.message) || t("This level could not be loaded."), "error");
      });
  };

  OutlineView.prototype.announce = function () {
    var total = this.topSection.total;

    this.status.textContent = total
      ? core.format(generic().nt("%(count)s record", "%(count)s records", total), { count: number(total) })
      : "";
  };

  /* -- Rows ------------------------------------------------------------- */

  /** A cell's content, as its table draws it. */
  OutlineView.prototype.fill = function (target, column, row) {
    var data = row[column.data];

    target.textContent = "";

    if (typeof column.render === "function") {
      // The table's own renderers: they escape what they draw.
      target.innerHTML = column.render(data, "display", row) || "";
    } else if (data !== null && data !== undefined) {
      target.textContent = String(data);
    }
  };

  OutlineView.prototype.rowOf = function (node) {
    if (node.element) {
      this.updateRow(node);
      return node.element;
    }

    var self = this;
    var level = node.level;
    var row = el("tr", "tree-row outline-row");
    var tools = el("td", "tree-table__tools");
    var leaf = !level.children.length;

    row.setAttribute("role", "row");
    row.setAttribute("aria-level", String(node.depth + 1));
    row.setAttribute("data-depth", String(node.depth));
    row.tabIndex = -1;
    row.outlineNode = node;
    tint(row, level);

    for (var index = 0; index < this.width; index += 1) {
      var column = level.columns[index];
      var td = el("td");
      var holder = td;

      if (index === 0) {
        var inner = el("div", "tree-row__inner");
        var toggle = el("button", "tree-row__toggle");
        var count = el("span", "tree-row__count");

        td.className = "tree-row__label";
        inner.style.paddingInlineStart = node.depth * 1.25 + "rem";
        toggle.type = "button";
        toggle.tabIndex = -1;
        toggle.addEventListener("click", function () {
          self.toggle(node);
        });
        holder = el("div", "outline-row__value");

        if (level.movable) {
          var handle = el("span", "outline-row__handle");

          handle.title = t("Drag to put in another order");
          handle.setAttribute("aria-hidden", "true");
          handle.appendChild(icon("drag_indicator"));
          inner.appendChild(handle);
        }

        inner.append(toggle, holder, count);
        td.appendChild(inner);
        node.toggleButton = toggle;
        node.countBadge = count;
        toggle.hidden = leaf;
      }

      if (column && this.isNumber(column)) {
        td.classList.add("tree-row__number");
      }

      if (column && column.className) {
        td.className += " " + column.className;
      }

      if (column) {
        node.cells.push({
          node: node,
          level: level,
          column: column,
          name: column.data,
          td: td,
          holder: holder,
          first: index === 0,
          writable: level.writes(column) && Boolean(widgets())
        });
      }

      row.appendChild(td);
    }

    if (node.url && core.isSafeUrl(node.url)) {
      var open = el("a", "icon-button icon-button--sm outline-row__open");

      open.href = node.url;
      open.tabIndex = -1;
      tools.appendChild(open);
      node.openLink = open;
    }

    row.appendChild(tools);
    row.addEventListener("click", function (event) {
      if (event.target === row || event.target.tagName === "TD") {
        self.focus(row);
      }
    });

    node.element = row;
    this.drawOpenLink(node);
    node.cells.forEach(function (cell) {
      self.drawCell(cell);

      if (cell.writable) {
        self.bindCell(cell);
      }
    });
    this.updateRow(node);

    return row;
  };

  /** The icon at the end of a row: the record's page, or - editing,
   * or its level opening in a dialog - its form in a dialog. */
  OutlineView.prototype.drawOpenLink = function (node) {
    var link = node.openLink;

    if (!link) {
      return;
    }

    var dialog = this.opensInDialog(node);
    var label = dialog ? t("Edit in a dialog") : t("Open");

    link.textContent = "";
    link.appendChild(icon(dialog ? "edit_square" : "open_in_new"));
    link.title = label;
    link.setAttribute("aria-label", label);
    link.classList.toggle("is-dialog", dialog);
  };

  /** A read-only cell; the first one links to the record's page. */
  OutlineView.prototype.drawCell = function (cell) {
    var node = cell.node;

    if (cell.first && node.url && core.isSafeUrl(node.url) && cell.column.displayType !== "link") {
      var anchor = el("a", "tree-row__name");

      anchor.href = node.url;
      anchor.tabIndex = -1;
      this.fill(anchor, cell.column, node.row);
      cell.holder.textContent = "";
      cell.holder.appendChild(anchor);

      return;
    }

    this.fill(cell.holder, cell.column, node.row);
  };

  /** The address adding a record of `section`'s relation to its
   * record, its `{parent}` filled in; "" for the top or a level adding
   * nothing. */
  OutlineView.prototype.addUrlBelow = function (section) {
    var level = section.level;
    var owner = section.owner;
    var url = level && level.addUrl && owner !== this.top ? level.addUrl.replace("{parent}", encodeURIComponent(owner.id)) : "";

    return url && core.isSafeUrl(url) ? url : "";
  };

  /** Whether `node` unfolds: it holds records, or - none yet - a
   * relation below can be added to, its foot offering the first one. */
  OutlineView.prototype.opens = function (node) {
    var self = this;

    return (
      node.count > 0 ||
      this.sectionsOf(node).some(function (section) {
        return Boolean(self.addUrlBelow(section));
      })
    );
  };

  OutlineView.prototype.updateRow = function (node) {
    var toggle = node.toggleButton;
    var expandable = this.opens(node);
    var loading = this.loadingOf(node);

    toggle.textContent = "";
    toggle.disabled = !expandable;
    toggle.classList.toggle("is-leaf", !expandable);

    if (expandable) {
      toggle.appendChild(
        icon(loading ? "progress_activity" : node.expanded ? "expand_more" : "chevron_right", loading ? "tree-row__spin" : "")
      );
      toggle.setAttribute("aria-label", node.expanded ? t("Fold") : t("Unfold"));
      node.element.setAttribute("aria-expanded", node.expanded ? "true" : "false");
      node.countBadge.textContent = number(node.count);
      node.countBadge.title = titlesBelow(node.level);
      node.countBadge.hidden = !node.count;
    } else {
      toggle.removeAttribute("aria-label");
      node.element.removeAttribute("aria-expanded");
      node.countBadge.hidden = true;
    }
  };

  /** A row spanning the table at the level of `section`. */
  OutlineView.prototype.levelRow = function (section, className) {
    var depth = section.owner.depth + 1;
    var row = el("tr", "tree-row " + className);
    var cell = el("td");
    var inner = el("div", "tree-row__inner tree-foot");

    row.setAttribute("data-depth", String(depth));
    tint(row, section.level);
    cell.colSpan = this.width + 1;
    inner.style.paddingInlineStart = depth * 1.25 + "rem";
    cell.appendChild(inner);
    row.appendChild(cell);
    row.inner = inner;

    return row;
  };

  /** The headings of a relation below a record: its name and its own
   * columns' titles. */
  OutlineView.prototype.headOf = function (section) {
    if (section.owner === this.top) {
      return null;
    }

    if (section.head) {
      return section.head;
    }

    var level = section.level;
    var depth = section.owner.depth + 1;
    var row = el("tr", "tree-row tree-row--head outline-head");

    row.setAttribute("data-depth", String(depth));
    tint(row, level);

    for (var index = 0; index < this.width; index += 1) {
      var column = level.columns[index];
      var th = el("td", "outline-head__cell");

      if (index === 0) {
        var inner = el("div", "tree-row__inner");

        inner.style.paddingInlineStart = depth * 1.25 + "rem";
        inner.append(icon("subdirectory_arrow_right", "muted"), el("span", "outline-head__level", level.title));

        if (column) {
          inner.appendChild(el("span", "outline-head__column", column.title));
        }

        th.appendChild(inner);
      } else if (column) {
        th.textContent = column.title;

        if (this.isNumber(column)) {
          th.classList.add("tree-row__number");
        }
      }

      row.appendChild(th);
    }

    row.appendChild(el("td", "outline-head__cell"));
    section.head = row;

    return row;
  };

  /** The row closing a relation: loading, failed, more to show, add. */
  OutlineView.prototype.footOf = function (section) {
    var self = this;
    var level = section.level;
    var shown = section.items.length;
    var more = section.total - shown;
    var addUrl = this.addUrlBelow(section);

    if (!section.loading && !section.failed && more <= 0 && shown && !addUrl) {
      return null;
    }

    var row = this.levelRow(section, "tree-row--foot");
    var rest = row.inner;

    if (section.loading) {
      rest.append(icon("progress_activity", "tree-row__spin"), el("span", "muted", t("Loading\u2026")));
    } else if (section.failed) {
      var retry = el("button", "button button--sm button--ghost", t("Try again"));

      retry.type = "button";
      retry.addEventListener("click", function () {
        self.load(section, false);
      });
      rest.append(el("span", "muted", t("This level could not be loaded.")), retry);
    } else {
      if (!shown) {
        rest.appendChild(el("span", "muted", t("Nothing here.")));
      } else if (more > 0) {
        var next = el("button", "button button--sm");

        next.type = "button";
        next.append(
          icon("expand_more"),
          el("span", "", core.format(t("Show %(count)s more"), { count: number(Math.min(more, self.pageSize)) }))
        );
        next.addEventListener("click", function () {
          self.load(section, true);
        });
        rest.append(el("span", "muted", core.format(t("%(shown)s of %(total)s"), { shown: number(shown), total: number(section.total) })), next);
      }

      if (addUrl) {
        var add = el("a", "button button--sm button--ghost");

        add.href = addUrl;
        add.append(icon("add"), el("span", "", core.format(t("Add %(name)s"), { name: level.label.toLowerCase() })));
        rest.appendChild(add);

        if (this.addsInDialog(level)) {
          add.addEventListener("click", function (event) {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
              return;
            }

            event.preventDefault();
            self.openAdd(section, addUrl);
          });
        }
      }
    }

    return row;
  };

  /** Every row below `node`, in order, as it should be drawn now: each
   * of its relations, headed, its records and theirs, then its foot. */
  OutlineView.prototype.rowsBelow = function (node) {
    var self = this;
    var rows = [];

    if (!node.expanded) {
      return rows;
    }

    var sections = this.shownSections(node);

    sections.forEach(function (section) {
      // Several relations: each named, even before its first record.
      var head = section.items.length || sections.length > 1 ? self.headOf(section) : null;

      if (head) {
        rows.push(head);
      }

      section.items.forEach(function (child) {
        rows.push(self.rowOf(child));
        rows = rows.concat(self.rowsBelow(child));
      });

      var foot = self.footOf(section);

      if (foot) {
        rows.push(foot);
      }
    });

    return rows;
  };

  /** Draw again what is below `parent`: the rows after its own with a
   * deeper level. Rows kept are moved, not rebuilt, so their controls
   * keep what is being typed in them. */
  OutlineView.prototype.redraw = function (parent) {
    var body = this.body;
    var stale = [];
    var next;

    if (parent.element) {
      this.updateRow(parent);
    }

    if (parent === this.top) {
      stale = Array.prototype.slice.call(body.children);
    } else if (parent.element && parent.element.parentNode) {
      next = parent.element.nextElementSibling;

      while (next && Number(next.getAttribute("data-depth")) > parent.depth) {
        stale.push(next);
        next = next.nextElementSibling;
      }
    } else {
      return;
    }

    var rows = this.rowsBelow(parent);
    var fragment = document.createDocumentFragment();

    stale.forEach(function (row) {
      if (rows.indexOf(row) === -1 && row.parentNode) {
        row.parentNode.removeChild(row);
      }
    });

    rows.forEach(function (row) {
      fragment.appendChild(row);
    });

    if (parent === this.top) {
      body.appendChild(fragment);
    } else {
      body.insertBefore(fragment, parent.element.nextSibling);
    }

    this.mountPending();
    stripe(body);

    if (!body.querySelector('tr[tabindex="0"]')) {
      var first = body.querySelector("tr.outline-row");

      if (first) {
        first.tabIndex = 0;
      }
    }

    this.drawExpandButton();
  };

  OutlineView.prototype.toggle = function (node, open) {
    var self = this;

    if (!this.opens(node)) {
      return;
    }

    node.expanded = open === undefined ? !node.expanded : Boolean(open);

    var waiting = node.expanded
      ? this.shownSections(node).filter(function (section) {
          return !section.loaded && !section.loading;
        })
      : [];

    if (!waiting.length) {
      this.redraw(node);
      return;
    }

    waiting.forEach(function (section) {
      self.load(section, false);
    });
  };

  /* -- Unfolding a level at once ---------------------------------------- */

  /** The records *Expand next level* unfolds: those of the shallowest
   * level shown holding records and still folded, in the order they
   * are drawn - the rows on screen first. */
  OutlineView.prototype.nextLevel = function () {
    var self = this;
    var depth = Infinity;
    var nodes = [];

    (function walk(parent) {
      (parent.sections || []).forEach(function (section) {
        section.items.forEach(function (node) {
          if (node.count > 0 && !node.expanded && !self.loadingOf(node)) {
            if (node.depth < depth) {
              depth = node.depth;
              nodes = [];
            }

            if (node.depth === depth) {
              nodes.push(node);
            }
          } else if (node.expanded && node.depth < depth) {
            walk(node);
          }
        });
      });
    })(this.top);

    return { depth: nodes.length ? depth : -1, nodes: nodes };
  };

  OutlineView.prototype.drawExpandButton = function () {
    var button = this.expandButton;

    if (!button) {
      return;
    }

    var next = this.nextLevel();
    var below = next.nodes.length ? titlesBelow(next.nodes[0].level) : "";
    var working = Boolean(this.expanding);
    // The first press unfolds the first level; once a record is open,
    // the next one - greyed out when nothing is left.
    var deeper = next.nodes.length
      ? next.depth > 0
      : this.topSection.items.some(function (node) {
          return node.expanded;
        });

    button.textContent = "";
    button.append(
      icon(working ? "progress_activity" : "unfold_more", working ? "tree-row__spin" : ""),
      el("span", "", deeper ? t("Expand next level") : t("Expand first level"))
    );
    button.disabled = working || !next.nodes.length;
    button.title = below
      ? core.format(t("Show the %(name)s of the rows shown"), { name: below.toLowerCase() })
      : t("Every row shown is unfolded");
  };

  /** Unfold the next level of every row shown, a few requests for all
   * of them: each record named gets its first page. */
  OutlineView.prototype.expandLevel = function () {
    var self = this;
    var nodes = this.nextLevel().nodes.slice(0, UNFOLD_AT_ONCE);
    var waiting = [];
    var byLevel = {};
    var chunks = [];

    if (this.expanding || !nodes.length) {
      return Promise.resolve();
    }

    nodes.forEach(function (node) {
      node.expanded = true;

      self.shownSections(node).forEach(function (section) {
        if (section.loaded || section.loading) {
          return;
        }

        // Nothing there yet: its foot offers the first one.
        if (!section.count) {
          section.loaded = true;
          return;
        }

        section.asking = {};
        section.loading = true;
        section.failed = false;
        waiting.push(section);
        (byLevel[section.level.index] = byLevel[section.level.index] || []).push(section);
      });

      self.redraw(node);
    });

    // One request names records of one relation: grouped by it, in the
    // order they are drawn.
    Object.keys(byLevel).forEach(function (key) {
      var sections = byLevel[key];

      for (var index = 0; index < sections.length; index += PARENTS_AT_ONCE) {
        chunks.push(sections.slice(index, index + PARENTS_AT_ONCE));
      }
    });

    this.expanding = true;
    this.drawExpandButton();

    return chunks
      .reduce(function (chain, chunk) {
        return chain.then(function () {
          return self.loadMany(chunk);
        });
      }, Promise.resolve())
      .catch(function (error) {
        waiting.forEach(function (section) {
          if (section.loading) {
            section.loading = false;
            section.failed = true;
            self.redraw(section.owner);
          }
        });
        generic().toast((error && error.message) || t("This level could not be loaded."), "error");
      })
      .then(function () {
        self.expanding = false;
        self.drawExpandButton();
      });
  };

  /** The first page of each of `sections`, one relation below several
   * records, in one request. */
  OutlineView.prototype.loadMany = function (sections) {
    var self = this;
    var asked = sections.map(function (section) {
      return { section: section, asking: section.asking };
    });
    var params = Object.assign(
      {},
      core.resolveExtraParams(this.controller.options, this.controller.table),
      {
        level: sections[0].level.index,
        limit: this.pageSize,
        parents: sections
          .map(function (section) {
            return section.owner.id;
          })
          .join(",")
      }
    );

    return generic()
      .api.get(this.config.url, params)
      .then(function (answer) {
        var groups = {};

        (answer.groups || []).forEach(function (group) {
          groups[String(group.parent)] = group;
        });

        asked.forEach(function (entry) {
          var section = entry.section;
          var group = groups[String(section.owner.id)];

          // Folded, unfolded again or gone since: its own answer counts.
          if (section.asking !== entry.asking) {
            return;
          }

          section.loading = false;

          if (!group) {
            // Out of this reader's sight now: folded again.
            section.owner.expanded = false;
          } else {
            section.items = (group.items || []).map(function (data) {
              return self.adopt(section, data, null);
            });
            section.total = group.total || 0;
            section.loaded = true;
          }

          self.redraw(section.owner);
        });
      });
  };

  OutlineView.prototype.collapseAll = function () {
    this.walk(function (node) {
      node.expanded = false;
    });
    this.redraw(this.top);
  };

  /** A node gone from its level: its controls go with it. */
  OutlineView.prototype.forget = function (node, deep) {
    var self = this;

    node.cells.forEach(function (cell) {
      cell.gone = true;

      if (cell.widget && cell.widget.destroy) {
        cell.widget.destroy();
      }
    });
    node.cells = [];

    if (node.element && node.element.parentNode) {
      node.element.parentNode.removeChild(node.element);
    }

    node.element = null;

    if (deep) {
      (node.sections || []).forEach(function (section) {
        section.items.forEach(function (child) {
          self.forget(child, true);
        });

        if (section.head && section.head.parentNode) {
          section.head.parentNode.removeChild(section.head);
        }
      });
    }
  };

  /* -- Editing ------------------------------------------------------------ */

  /** A control in every writable cell drawn and not mounted yet: a
   * Select2 field needs to be in the page to measure itself. */
  OutlineView.prototype.mountPending = function () {
    var self = this;

    Array.prototype.forEach.call(this.body.querySelectorAll("tr.outline-row"), function (row) {
      (row.outlineNode.cells || []).forEach(function (cell) {
        if (self.editing && cell.writable && !cell.widget) {
          self.mountCell(cell);
        }
      });
    });
  };

  OutlineView.prototype.mountCell = function (cell) {
    var helpers = cells();
    var schema = cell.level.editable[cell.name];
    var widget = widgets().create(schema, { compact: true });
    var row = cell.node.row;
    var value = helpers.valueOf(row, cell.name, schema);
    var editor = el("div", "cell-editor");

    cell.schema = schema;
    cell.widget = widget;
    cell.saved = value;
    cell.holder.textContent = "";
    cell.td.classList.add("grid-cell");
    editor.appendChild(widget.root);
    cell.holder.appendChild(editor);

    if (widget.focus && schema.label) {
      widget.focus.setAttribute("aria-label", schema.label);
    }

    if (widget.mount) {
      widget.mount();
    }

    widget.set(value, helpers.labelsOf(row, cell.name, schema, value));
    fitText(cell);
  };

  /**
   * A long text is as tall as what it holds, plus one line to write
   * on: one line when empty, two for one line, three for two - lines
   * wrapped by the cell's width count too.
   */
  function fitText(cell) {
    var area = cell.widget && cell.widget.focus;

    if (!area || area.tagName !== "TEXTAREA") {
      return;
    }

    var style = window.getComputedStyle(area);
    var line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4 || 20;
    var padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    var border = (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0);
    var lines = 0;

    area.rows = 1;
    area.style.height = "0px";

    if (area.value) {
      lines = Math.max(1, Math.round((area.scrollHeight - padding) / line));
    }

    area.style.height = Math.ceil((lines + 1) * line + padding + border) + "px";
  }

  /** Back to the value, drawn as the table draws it. */
  OutlineView.prototype.unmountCell = function (cell) {
    if (cell.widget && cell.widget.destroy) {
      cell.widget.destroy();
    }

    cell.widget = null;
    this.clearError(cell);
    cell.td.classList.remove("grid-cell", "is-saving");
    this.drawCell(cell);
  };

  /** Listened to once, whether the control is there or not. */
  OutlineView.prototype.bindCell = function (cell) {
    var self = this;
    var helpers = cells();

    function changed() {
      if (cell.widget) {
        self.commit(cell);
      }
    }

    cell.td.addEventListener("input", function () {
      fitText(cell);
    });
    cell.td.addEventListener("focusin", function () {
      fitText(cell);
    });
    cell.td.addEventListener("change", changed);
    cell.td.addEventListener("generic:change", changed);
    cell.td.addEventListener("focusout", function () {
      window.setTimeout(function () {
        if (!cell.gone && cell.widget && !focusWithin(cell.td)) {
          self.commit(cell);
        }
      }, 0);
    });
    cell.td.addEventListener("keydown", function (event) {
      if (!cell.widget) {
        return;
      }

      var target = event.target;
      var typed = target.tagName === "INPUT" && target.type !== "checkbox" && target.type !== "radio";

      if (event.key === "Enter" && typed) {
        event.preventDefault();
        self.commit(cell);
      } else if (event.key === "Escape") {
        cell.widget.set(cell.saved, helpers.labelsOf(cell.node.row, cell.name, cell.schema, cell.saved));
        fitText(cell);
        self.clearError(cell);
      }

      // The row's keys move between rows; inside a control they type.
      event.stopPropagation();
    });
  };

  OutlineView.prototype.clearError = function (cell) {
    cell.td.classList.remove("is-invalid");

    if (cell.error) {
      cell.error.remove();
      cell.error = null;
    }
  };

  OutlineView.prototype.showError = function (cell, error) {
    var detail = error && error.data;
    var messages = detail && detail[cell.name];
    var message = Array.isArray(messages)
      ? messages.join(" ")
      : messages || (detail && detail.detail) || (error && error.message) || t("This could not be saved.");

    cell.td.classList.add("is-invalid");

    if (!cell.error) {
      cell.error = el("div", "cell-editor__error");
      cell.holder.appendChild(cell.error);
    }

    cell.error.textContent = message;
  };

  OutlineView.prototype.commit = function (cell) {
    var self = this;
    var helpers = cells();
    var value = cell.widget.get();
    var node = cell.node;

    if (helpers.sameValue(cell.saved, value)) {
      this.clearError(cell);
      return;
    }

    if (cell.saving) {
      cell.pending = true;
      return;
    }

    var url = core.fillTemplate(cell.level.editableUrl, node.row);

    if (!url) {
      return;
    }

    var body = {};

    body[cell.name] = value;
    cell.saving = true;
    cell.td.classList.add("is-saving");
    this.recentWrites[cell.level.resource + ":" + node.id] = Date.now();

    generic()
      .api.patch(url, body)
      .then(function (fresh) {
        if (cell.gone) {
          return;
        }

        Object.assign(node.row, fresh);

        var saved = helpers.valueOf(node.row, cell.name, cell.schema);

        if (helpers.sameValue(cell.widget.get(), value)) {
          cell.widget.set(saved, helpers.labelsOf(node.row, cell.name, cell.schema, saved));
          fitText(cell);
        }

        cell.saved = saved;
        self.clearError(cell);
        self.refreshRow(node, cell);
        helpers.flash(cell.td);
      })
      .catch(function (error) {
        if (!cell.gone) {
          self.showError(cell, error);
        }
      })
      .then(function () {
        cell.saving = false;
        cell.td.classList.remove("is-saving");

        if (cell.pending && !cell.gone) {
          cell.pending = false;
          self.commit(cell);
        }
      });
  };

  /** The rest of a row, from the server's answer: a change often moves
   * more than the cell it was typed in. */
  OutlineView.prototype.refreshRow = function (node, written) {
    var self = this;
    var helpers = cells();

    node.cells.forEach(function (cell) {
      if (cell === written) {
        return;
      }

      if (!cell.widget) {
        self.drawCell(cell);
        return;
      }

      if (focusWithin(cell.td)) {
        return;
      }

      var value = helpers.valueOf(node.row, cell.name, cell.schema);

      if (!helpers.sameValue(cell.saved, value)) {
        cell.saved = value;
        cell.widget.set(value, helpers.labelsOf(node.row, cell.name, cell.schema, value));
        fitText(cell);
      }
    });
  };

  /** Whether the outline is in use: a control has the focus, a list is
   * open, a cell is on its way. A reload now would take the work. */
  OutlineView.prototype.busy = function () {
    var busy = focusWithin(this.body) || Boolean(document.querySelector(".select2-container--open"));

    if (busy) {
      return true;
    }

    return this.body.querySelectorAll("td.is-saving").length > 0;
  };

  /* -- Loading again ------------------------------------------------------ */

  /** Load again every relation that is open, keeping it open. */
  OutlineView.prototype.reload = function () {
    var self = this;
    var open = [];

    function walk(node) {
      if (!node.expanded) {
        return;
      }

      (node.sections || []).forEach(function (section) {
        if (section.loaded) {
          open.push(section);
          section.items.forEach(walk);
        }
      });
    }

    walk(this.top);

    return open.reduce(function (chain, section) {
      return chain.then(function () {
        var owner = section.owner;

        if (owner !== self.top && !(owner.element && owner.element.parentNode)) {
          return null;
        }

        return self.load(section, false, Math.min(200, Math.max(self.pageSize, section.items.length)));
      });
    }, Promise.resolve());
  };

  /** Load again when a record of one of the levels changes elsewhere. */
  OutlineView.prototype.listen = function () {
    var self = this;
    var Generic = generic();
    var resources = this.levels.map(function (level) {
      return level.resource;
    });
    var waiting = false;

    if (!Generic.events || !(this.config.topics || []).length) {
      return;
    }

    function run() {
      if (!self.active) {
        waiting = false;
        return;
      }

      if (self.busy()) {
        waiting = true;
        return;
      }

      waiting = false;
      self.reload();
    }

    var later = Generic.debounce(run, 600);

    this.config.topics.forEach(function (topic) {
      Generic.events.subscribe(topic);
    });
    Generic.events.on("resource.changed", function (payload) {
      if (payload && payload.resource && resources.indexOf(payload.resource) === -1) {
        return;
      }

      var at = payload ? self.recentWrites[payload.resource + ":" + payload.id] : 0;

      if (at && Date.now() - at < OWN_WRITE_MS) {
        return;
      }

      later();
    });

    // Put down: what waited runs.
    this.body.addEventListener("focusout", function () {
      window.setTimeout(function () {
        if (waiting && !self.busy()) {
          run();
        }
      }, 0);
    });
  };

  /* -- A record in a dialog ---------------------------------------------- */

  OutlineView.prototype.opensInDialog = function (node) {
    var level = node.level;

    return Boolean(
      level &&
        level.changeUrl &&
        (this.editing || level.openInDialog) &&
        generic().dialogs &&
        generic().dialogs.record
    );
  };

  /** The record's whole form, over the outline: what its row does not
   * show - a long text, the fields of its own - is written there. Once
   * it is saved, its section is read again - the records that were
   * open kept so - and so are its own relations that were open. */
  OutlineView.prototype.openRecord = function (node) {
    var self = this;
    var level = node.level;
    var url = level.changeUrl.replace("{id}", encodeURIComponent(node.id));

    if (!core.isSafeUrl(url)) {
      return;
    }

    generic()
      .dialogs.record({ url: url, title: level.label, icon: "edit" })
      .then(function (result) {
        if (!result) {
          return;
        }

        var parent = node.parent || self.topSection;

        self.recentWrites[level.resource + ":" + node.id] = Date.now();

        if (result.saved) {
          generic().toast(core.format(t("\u201c%(name)s\u201d was saved."), { name: result.label || String(node.id) }), "success");
        }

        return self.load(parent, false, self.limitOf(parent)).then(function () {
          // Found again, in the place of the one opened.
          var again =
            parent.items.filter(function (item) {
              return String(item.id) === String(node.id);
            })[0] || null;
          var open = again && again.expanded ? (again.sections || []).filter(function (section) {
            return section.loaded;
          }) : [];

          return Promise.all(
            open.map(function (section) {
              return self.load(section, false, self.limitOf(section));
            })
          ).then(function () {
            var row = (again || node).element;

            if (row && row.parentNode) {
              row.focus();
            }
          });
        });
      });
  };

  /** As many records as `section` shows, to read it again whole. */
  OutlineView.prototype.limitOf = function (section) {
    return Math.min(200, Math.max(this.pageSize, section.items.length));
  };

  OutlineView.prototype.addsInDialog = function (level) {
    return Boolean(level && level.addInDialog && generic().dialogs && generic().dialogs.record);
  };

  /** A new record of `section`'s relation, its form over the outline:
   * once it is saved, the relation is read again - open, and the
   * records below it that were open kept so - and its count follows. */
  OutlineView.prototype.openAdd = function (section, url) {
    var self = this;
    var level = section.level;

    return generic()
      .dialogs.record({ url: url, title: core.format(t("Add %(name)s"), { name: level.label.toLowerCase() }), icon: "add" })
      .then(function (result) {
        if (!result || !result.saved) {
          return null;
        }

        // Its own event, already drawn here: not read a second time.
        if (result.id !== undefined && result.id !== "") {
          self.recentWrites[level.resource + ":" + result.id] = Date.now();
        }

        var owner = section.owner;

        owner.expanded = true;
        generic().toast(core.format(t("\u201c%(name)s\u201d was added."), { name: result.label || String(result.id) }), "success");

        return self.load(section, false, Math.min(200, Math.max(self.pageSize, section.items.length + 1))).then(function () {
          if (section.failed) {
            return;
          }

          var place = (owner.sections || []).indexOf(section);

          section.count = section.total;

          if (place !== -1) {
            owner.counts[place] = section.total;
          }

          owner.count = owner.counts.reduce(function (sum, value) {
            return sum + (Number(value) || 0);
          }, 0);

          if (owner.element) {
            self.updateRow(owner);
          }
        });
      });
  };

  /* -- Another order ------------------------------------------------------ */

  /** Whether the record can be dragged now: its level keeps an order of
   * its own, and the outline is being edited. */
  OutlineView.prototype.movesNow = function (node) {
    var level = node.level;

    return Boolean(this.editing && level && level.movable && node.parent && node.parent.owner !== this.top);
  };

  /** Put `node` before or after another record of its parent: written,
   * then drawn in the order the server answers. */
  OutlineView.prototype.move = function (node, where) {
    var self = this;
    var parent = node.parent;
    var url = new URL(this.config.moveUrl, window.location.origin);
    var body = { level: node.level.index, parent: parent.owner.id, id: node.id };
    var extra = core.resolveExtraParams(this.controller.options, this.controller.table);

    if (!this.config.moveUrl || !core.isSafeUrl(this.config.moveUrl)) {
      return Promise.resolve();
    }

    Object.keys(extra).forEach(function (key) {
      url.searchParams.set(key, extra[key]);
    });

    if (where.before) {
      body.before = where.before.id;
    } else if (where.after) {
      body.after = where.after.id;
    }

    this.recentWrites[node.level.resource + ":" + node.id] = Date.now();
    node.element.classList.add("is-saving");

    return generic()
      .api.post(url.pathname + url.search, body)
      .then(function (answer) {
        var order = (answer && answer.order) || [];
        var rank = {};

        order.forEach(function (key, index) {
          rank[String(key)] = index;
        });
        parent.items.sort(function (a, b) {
          var left = String(a.id) in rank ? rank[String(a.id)] : Infinity;
          var right = String(b.id) in rank ? rank[String(b.id)] : Infinity;

          return left - right;
        });
        self.redraw(parent.owner);

        if (node.element) {
          cells().flash(node.element);
          self.focus(node.element);
        }
      })
      .catch(function (error) {
        generic().toast((error && error.message) || t("This could not be saved."), "error");
        self.load(parent, false, Math.min(200, Math.max(self.pageSize, parent.items.length)));
      })
      .then(function () {
        if (node.element) {
          node.element.classList.remove("is-saving");
        }
      });
  };

  /** Rows dragged by their handle, among their parent's records. */
  OutlineView.prototype.bindDragging = function () {
    var self = this;
    var body = this.body;

    function rowAt(event) {
      var row = event.target.closest && event.target.closest("tr.outline-row");

      return row && row.outlineNode ? row : null;
    }

    function clearMarks() {
      Array.prototype.forEach.call(body.querySelectorAll(".is-drop-before, .is-drop-after"), function (row) {
        row.classList.remove("is-drop-before", "is-drop-after");
      });
    }

    function target(event) {
      var row = rowAt(event);
      var dragged = self.dragging;

      if (!row || !dragged || row.outlineNode === dragged || row.outlineNode.parent !== dragged.parent) {
        return null;
      }

      var box = row.getBoundingClientRect();

      return { row: row, after: event.clientY > box.top + box.height / 2 };
    }

    body.addEventListener("mousedown", function (event) {
      var handle = event.target.closest && event.target.closest(".outline-row__handle");
      var row = handle && rowAt(event);

      if (row && self.movesNow(row.outlineNode)) {
        row.draggable = true;
      }
    });

    body.addEventListener("dragstart", function (event) {
      var row = rowAt(event);

      if (!row || !row.draggable) {
        return;
      }

      self.dragging = row.outlineNode;
      row.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(row.outlineNode.id));
    });

    body.addEventListener("dragover", function (event) {
      var place = target(event);

      clearMarks();

      if (!place) {
        return;
      }

      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      place.row.classList.add(place.after ? "is-drop-after" : "is-drop-before");
    });

    body.addEventListener("drop", function (event) {
      var place = target(event);
      var dragged = self.dragging;

      clearMarks();

      if (!place) {
        return;
      }

      event.preventDefault();
      self.move(dragged, place.after ? { after: place.row.outlineNode } : { before: place.row.outlineNode });
    });

    body.addEventListener("dragend", function (event) {
      var row = rowAt(event);

      clearMarks();

      if (row) {
        row.draggable = false;
        row.classList.remove("is-dragging");
      }

      self.dragging = null;
    });

    document.addEventListener("mouseup", function () {
      if (!self.dragging) {
        Array.prototype.forEach.call(body.querySelectorAll("tr[draggable='true']"), function (row) {
          row.draggable = false;
        });
      }
    });
  };

  /* -- The keyboard: a treegrid's ---------------------------------------- */

  OutlineView.prototype.rows = function () {
    return Array.prototype.slice.call(this.body.querySelectorAll("tr.outline-row"));
  };

  OutlineView.prototype.focus = function (row) {
    if (!row) {
      return;
    }

    this.rows().forEach(function (other) {
      other.tabIndex = other === row ? 0 : -1;
    });
    row.focus();
  };

  OutlineView.prototype.keydown = function (event) {
    var row = event.target;

    if (!row || row.tagName !== "TR" || !row.outlineNode) {
      return;
    }

    var node = row.outlineNode;
    var rows = this.rows();
    var index = rows.indexOf(row);
    var handled = true;

    // Alt and an arrow: the record changes places with its neighbour.
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      var siblings = node.parent ? node.parent.items : [];
      var at = siblings.indexOf(node);
      var other = siblings[event.key === "ArrowUp" ? at - 1 : at + 1];

      if (this.movesNow(node) && other) {
        this.move(node, event.key === "ArrowUp" ? { before: other } : { after: other });
      }

      event.preventDefault();
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        this.focus(rows[index + 1]);
        break;
      case "ArrowUp":
        this.focus(rows[index - 1]);
        break;
      case "Home":
        this.focus(rows[0]);
        break;
      case "End":
        this.focus(rows[rows.length - 1]);
        break;
      case "ArrowRight":
        if (this.opens(node) && !node.expanded) {
          this.toggle(node, true);
        } else if (node.expanded) {
          var first = this.shownSections(node).filter(function (section) {
            return section.items.length;
          })[0];

          if (first) {
            this.focus(first.items[0].element);
          }
        }
        break;
      case "ArrowLeft":
        if (node.expanded) {
          this.toggle(node, false);
        } else if (node.parent && node.parent.owner.element) {
          this.focus(node.parent.owner.element);
        }
        break;
      case "Enter":
        if (this.opensInDialog(node)) {
          this.openRecord(node);
        } else if (node.url && core.isSafeUrl(node.url)) {
          window.location.href = node.url;
        }
        break;
      case " ":
        this.toggle(node);
        break;
      default:
        handled = false;
    }

    if (handled) {
      event.preventDefault();
    }
  };

  /* -- The feature --------------------------------------------------------- */

  function buildButton(view) {
    var config = view.config;
    var label = config.title || t("Outline");
    var button = el("button", "button button--sm dt-tool dt-outline-toggle");

    button.type = "button";
    button.append(icon(config.icon || "account_tree"), el("span", "dt-tool__label", label));
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", function () {
      view.show(!view.active);
      remember(view.controller, view.active);
    });

    return button;
  }

  function placeButton(controller, button) {
    var tools = controller.slots.tools;

    if (!tools) {
      return;
    }

    // Beside the other ways of seeing the rows: after the chart, before
    // the saved views.
    var before = tools.querySelector(":scope > .dt-menu") || tools.lastElementChild;

    tools.insertBefore(button, before);
  }

  core.registerFeature({
    name: "outline",

    enabled: function (controller) {
      var config = controller.options.outline;

      return Boolean(config && config.url && (config.levels || []).length > 1 && generic() && generic().api);
    },

    init: function (controller) {
      var view = new OutlineView(controller, controller.options.outline);
      var api = controller.instance;

      controller.outline = view;
      view.button = buildButton(view);
      placeButton(controller, view.button);
      view.place();
      view.listen();

      // The table answered a new selection: the first level follows.
      api.on("xhr.dt.outline", function () {
        view.follow();
      });

      if (editingFirst(controller)) {
        view.setEditing(true);
      }

      if (remembered(controller)) {
        view.show(true);
      }
    },

    destroy: function (controller) {
      if (controller.outline) {
        controller.outline.forget(controller.outline.top, true);
        controller.outline.root.remove();
        controller.outline = null;
      }

      controller.instance.off(".outline");
    }
  });

  namespace.outline = { OutlineView: OutlineView };
})(window, document);

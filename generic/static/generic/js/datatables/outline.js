/**
 * A list unfolding into its related records, edited where they stand
 * (generic.sites.outlines).
 *
 * The table's toolbar gets an "Outline" button. Pressed, the rows make
 * way for a tree drawn like the tree pages (css/tree.css): the table's
 * records first - its filters, search and order still apply - each
 * with an arrow to the records of the next level, which have one to
 * theirs. Nothing is fetched before it is unfolded: a level is one
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

  function focusWithin(node) {
    return Boolean(node && node.contains(document.activeElement));
  }

  function storageKey(controller) {
    return "generic.outline." + (controller.options.stateKey || controller.url);
  }

  function remembered(controller) {
    try {
      if (new URLSearchParams(window.location.search).get(URL_PARAM) === "1") {
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

    if (!window.history || !window.history.replaceState) {
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
    this.index = index;
    this.name = config.name;
    this.resource = config.resource;
    this.title = config.title || "";
    this.label = config.label || "";
    this.columns = columnsModule.normalizeColumns(config.columns || []);
    this.editable = config.editable || {};
    this.editableUrl = config.editableUrl || "";
    this.addUrl = config.addUrl || "";
    this.rowKey = config.rowKey || "_pk";
  }

  Level.prototype.writes = function (column) {
    return Boolean(this.editableUrl && column.data && this.editable[column.data]);
  };

  /* -- The outline -------------------------------------------------------- */

  function OutlineView(controller, config) {
    this.controller = controller;
    this.config = config;
    this.pageSize = config.pageSize || 25;
    this.levels = (config.levels || []).map(function (level, index) {
      return new Level(level, index);
    });
    this.width = Math.max.apply(
      null,
      this.levels.map(function (level) {
        return Math.max(1, level.columns.length);
      })
    );
    this.top = this.node({ id: null }, -1);
    this.top.expanded = true;
    this.recentWrites = {};
    this.editable = this.levels.some(function (level) {
      return Object.keys(level.editable).length > 0 && Boolean(level.editableUrl);
    }) && Boolean(widgets());
    this.editing = false;
    this.active = false;
    this.asked = "";
    this.build();
  }

  OutlineView.prototype.node = function (data, depth) {
    return {
      id: data.id,
      url: data.url || "",
      row: data.row || {},
      count: data.children || 0,
      depth: depth,
      expanded: false,
      loaded: false,
      loading: false,
      failed: false,
      items: [],
      total: 0,
      parent: null,
      element: null,
      cells: [],
      head: null
    };
  };

  OutlineView.prototype.build = function () {
    var self = this;
    var root = el("div", "generic-tree dt-outline");
    var toolbar = el("div", "tree__toolbar");
    var status = el("span", "tree__status muted");
    var collapse = el("button", "button button--sm button--ghost");
    var refresh = el("button", "button button--sm button--ghost");

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

    toolbar.append(collapse, refresh);

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

    table.append(head, this.body);
    scroller.appendChild(table);
    root.append(toolbar, scroller);
    root.hidden = true;

    this.root = root;
    this.status = status;
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

    this.top.items.forEach(function walk(node) {
      node.cells.forEach(function (cell) {
        if (!cell.writable) {
          return;
        }

        if (!self.editing && cell.widget) {
          self.unmountCell(cell);
        }
      });
      node.items.forEach(walk);
    });

    if (this.editing) {
      this.mountPending();
    }
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

    if (key === this.asked && this.top.loaded) {
      return;
    }

    this.asked = key;
    this.load(this.top, false);
  };

  /* -- Fetching ----------------------------------------------------------- */

  OutlineView.prototype.fetch = function (parent, offset, limit) {
    var params = { level: parent.depth + 1, offset: offset, limit: limit || this.pageSize };

    if (parent === this.top) {
      Object.assign(params, this.tableParams());
    } else {
      params.parent = parent.id;
    }

    return generic().api.get(this.config.url, params);
  };

  OutlineView.prototype.adopt = function (parent, data, before) {
    var child = this.node(data, parent.depth + 1);

    child.parent = parent;

    // Found again: it stays open, its rows kept.
    if (before && before.expanded && child.count) {
      child.expanded = true;
      child.loaded = before.loaded;
      child.items = before.items;
      child.total = before.total;
      child.head = before.head;
      child.items.forEach(function (item) {
        item.parent = child;
      });
    }

    if (before) {
      this.forget(before, false);
    }

    return child;
  };

  /** Fill `parent` with the page asked for: replaced, or added to. */
  OutlineView.prototype.load = function (parent, append, limit) {
    var self = this;
    var offset = append ? parent.items.length : 0;
    var asking = {};

    parent.asking = asking;
    parent.loading = true;
    parent.failed = false;
    this.redraw(parent);

    return this.fetch(parent, offset, limit)
      .then(function (answer) {
        if (parent.asking !== asking) {
          return;
        }

        var known = {};

        if (!append) {
          parent.items.forEach(function (child) {
            known[child.id] = child;
          });
          parent.items = [];
        }

        (answer.items || []).forEach(function (data) {
          parent.items.push(self.adopt(parent, data, known[data.id]));
          delete known[data.id];
        });

        Object.keys(known).forEach(function (key) {
          self.forget(known[key], true);
        });

        parent.total = answer.total || 0;
        parent.loaded = true;
        parent.loading = false;

        if (parent === self.top) {
          self.announce();
        }

        self.redraw(parent);
      })
      .catch(function (error) {
        if (parent.asking !== asking) {
          return;
        }

        parent.loading = false;
        parent.failed = true;
        self.redraw(parent);
        generic().toast((error && error.message) || t("This level could not be loaded."), "error");
      });
  };

  OutlineView.prototype.announce = function () {
    var total = this.top.total;

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
    var level = this.levels[node.depth];
    var row = el("tr", "tree-row outline-row");
    var tools = el("td", "tree-table__tools");
    var leaf = node.depth >= this.levels.length - 1;

    row.setAttribute("role", "row");
    row.setAttribute("aria-level", String(node.depth + 1));
    row.setAttribute("data-depth", String(node.depth));
    row.tabIndex = -1;
    row.outlineNode = node;

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
      var open = el("a", "icon-button icon-button--sm");

      open.href = node.url;
      open.title = t("Open");
      open.setAttribute("aria-label", t("Open"));
      open.tabIndex = -1;
      open.appendChild(icon("open_in_new"));
      tools.appendChild(open);
    }

    row.appendChild(tools);
    row.addEventListener("click", function (event) {
      if (event.target === row || event.target.tagName === "TD") {
        self.focus(row);
      }
    });

    node.element = row;
    node.cells.forEach(function (cell) {
      self.drawCell(cell);

      if (cell.writable) {
        self.bindCell(cell);
      }
    });
    this.updateRow(node);

    return row;
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

  OutlineView.prototype.updateRow = function (node) {
    var toggle = node.toggleButton;
    var expandable = node.count > 0;

    toggle.textContent = "";
    toggle.disabled = !expandable;
    toggle.classList.toggle("is-leaf", !expandable);

    if (expandable) {
      toggle.appendChild(
        icon(node.loading ? "progress_activity" : node.expanded ? "expand_more" : "chevron_right", node.loading ? "tree-row__spin" : "")
      );
      toggle.setAttribute("aria-label", node.expanded ? t("Fold") : t("Unfold"));
      node.element.setAttribute("aria-expanded", node.expanded ? "true" : "false");
      node.countBadge.textContent = number(node.count);
      node.countBadge.title = this.levels[node.depth + 1] ? this.levels[node.depth + 1].title : "";
      node.countBadge.hidden = false;
    } else {
      toggle.removeAttribute("aria-label");
      node.element.removeAttribute("aria-expanded");
      node.countBadge.hidden = true;
    }
  };

  /** A row spanning the table at the level below `parent`. */
  OutlineView.prototype.levelRow = function (parent, className) {
    var row = el("tr", "tree-row " + className);
    var cell = el("td");
    var inner = el("div", "tree-row__inner tree-foot");

    row.setAttribute("data-depth", String(parent.depth + 1));
    cell.colSpan = this.width + 1;
    inner.style.paddingInlineStart = (parent.depth + 1) * 1.25 + "rem";
    cell.appendChild(inner);
    row.appendChild(cell);
    row.inner = inner;

    return row;
  };

  /** The headings of a level below the top: its own columns' titles. */
  OutlineView.prototype.headOf = function (parent) {
    if (parent === this.top) {
      return null;
    }

    if (parent.head) {
      return parent.head;
    }

    var level = this.levels[parent.depth + 1];
    var row = el("tr", "tree-row tree-row--head outline-head");

    row.setAttribute("data-depth", String(parent.depth + 1));

    for (var index = 0; index < this.width; index += 1) {
      var column = level.columns[index];
      var th = el("td", "outline-head__cell");

      if (index === 0) {
        var inner = el("div", "tree-row__inner");

        inner.style.paddingInlineStart = (parent.depth + 1) * 1.25 + "rem";
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
    parent.head = row;

    return row;
  };

  /** The row closing a level: loading, failed, more to show, add. */
  OutlineView.prototype.footOf = function (parent) {
    var self = this;
    var level = this.levels[parent.depth + 1];
    var shown = parent.items.length;
    var more = parent.total - shown;
    var addUrl = level && level.addUrl && parent !== this.top ? level.addUrl.replace("{parent}", encodeURIComponent(parent.id)) : "";

    if (addUrl && !core.isSafeUrl(addUrl)) {
      addUrl = "";
    }

    if (!parent.loading && !parent.failed && more <= 0 && shown && !addUrl) {
      return null;
    }

    var row = this.levelRow(parent, "tree-row--foot");
    var rest = row.inner;

    if (parent.loading) {
      rest.append(icon("progress_activity", "tree-row__spin"), el("span", "muted", t("Loading\u2026")));
    } else if (parent.failed) {
      var retry = el("button", "button button--sm button--ghost", t("Try again"));

      retry.type = "button";
      retry.addEventListener("click", function () {
        self.load(parent, false);
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
          self.load(parent, true);
        });
        rest.append(el("span", "muted", core.format(t("%(shown)s of %(total)s"), { shown: number(shown), total: number(parent.total) })), next);
      }

      if (addUrl) {
        var add = el("a", "button button--sm button--ghost");

        add.href = addUrl;
        add.append(icon("add"), el("span", "", core.format(t("Add %(name)s"), { name: level.label.toLowerCase() })));
        rest.appendChild(add);
      }
    }

    return row;
  };

  /** Every row below `parent`, in order, as it should be drawn now. */
  OutlineView.prototype.rowsBelow = function (parent) {
    var self = this;
    var rows = [];

    if (!parent.expanded) {
      return rows;
    }

    var head = parent.items.length ? this.headOf(parent) : null;

    if (head) {
      rows.push(head);
    }

    parent.items.forEach(function (child) {
      rows.push(self.rowOf(child));
      rows = rows.concat(self.rowsBelow(child));
    });

    var foot = this.footOf(parent);

    if (foot) {
      rows.push(foot);
    }

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

    if (!body.querySelector('tr[tabindex="0"]')) {
      var first = body.querySelector("tr.outline-row");

      if (first) {
        first.tabIndex = 0;
      }
    }
  };

  OutlineView.prototype.toggle = function (node, open) {
    if (!node.count) {
      return;
    }

    node.expanded = open === undefined ? !node.expanded : Boolean(open);

    if (node.expanded && !node.loaded) {
      this.load(node, false);
      return;
    }

    this.redraw(node);
  };

  OutlineView.prototype.collapseAll = function () {
    this.top.items.forEach(function walk(node) {
      node.expanded = false;
      node.items.forEach(walk);
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
      node.items.forEach(function (child) {
        self.forget(child, true);
      });

      if (node.head && node.head.parentNode) {
        node.head.parentNode.removeChild(node.head);
      }
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
  };

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

  /** Load again every level that is open, keeping it open. */
  OutlineView.prototype.reload = function () {
    var self = this;
    var open = [];

    function walk(node) {
      if (node.expanded && node.loaded) {
        open.push(node);
        node.items.forEach(walk);
      }
    }

    walk(this.top);

    return open.reduce(function (chain, node) {
      return chain.then(function () {
        if (node !== self.top && !(node.element && node.element.parentNode)) {
          return null;
        }

        return self.load(node, false, Math.min(200, Math.max(self.pageSize, node.items.length)));
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
        if (node.count && !node.expanded) {
          this.toggle(node, true);
        } else if (node.expanded && node.items.length) {
          this.focus(node.items[0].element);
        }
        break;
      case "ArrowLeft":
        if (node.expanded) {
          this.toggle(node, false);
        } else if (node.parent && node.parent.element) {
          this.focus(node.parent.element);
        }
        break;
      case "Enter":
        if (node.url && core.isSafeUrl(node.url)) {
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

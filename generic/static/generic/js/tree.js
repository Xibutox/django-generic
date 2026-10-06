/**
 * A tree of records that unfolds a level at a time (generic.sites.trees).
 *
 * Nothing is fetched before it is needed: opening a record asks the
 * tree's endpoint for the first page of what it holds, "Show more" for
 * the next, and a level holding more than a page gets a search box of
 * its own - so a level of several thousand records costs what a level
 * of fifty does. Rows are one flat table: a record's children are the
 * rows after it with a deeper level, which is also what the keyboard
 * walks.
 *
 *   <div class="generic-tree" data-config="<id of a json_script>"></div>
 *   Generic.tree.start(element)
 *
 * Every value reaches the page through textContent, every address
 * through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

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

  function el(tag, className, text) {
    var element = document.createElement(tag);

    if (className) {
      element.className = className;
    }

    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }

    return element;
  }

  function icon(name, extra) {
    var element = el("span", "icon material-symbols-outlined icon--sm" + (extra ? " " + extra : ""), name);

    element.setAttribute("aria-hidden", "true");

    return element;
  }

  function number(value) {
    try {
      return Number(value).toLocaleString(document.documentElement.lang || undefined);
    } catch (error) {
      return String(value);
    }
  }

  function link(url, text) {
    if (url && Generic.isSafeUrl(url)) {
      var anchor = el("a", "", text);

      anchor.href = url;

      return anchor;
    }

    return el("span", "", text);
  }

  /* -- Values, typed as a summary page types them ----------------------- */

  function tag(entry) {
    var colors = Generic.colors;
    var background = colors.clean(entry.background);
    var color = colors.clean(entry.color);
    var element = link(entry.url, entry.label);

    element.className = background ? "tag tag--solid" : "tag";

    if (background) {
      element.style.setProperty("--tag-background", background);
      element.style.setProperty("--tag-text", color || colors.readableOn(background));
    } else if (color) {
      element.style.setProperty("--tag-color", color);
    }

    if (entry.title) {
      element.title = entry.title;
    }

    return element;
  }

  function value(entry) {
    entry = entry || { empty: true };

    var wrapper = el("span", "tree-value tree-value--" + (entry.type || "text"));

    if (entry.empty) {
      wrapper.appendChild(el("span", "muted", "\u2014"));
      return wrapper;
    }

    switch (entry.type) {
      case "boolean":
        var yes = Boolean(entry.value);
        var flag = el("span", "dt-boolean " + (yes ? "dt-boolean--yes" : "dt-boolean--no"));

        flag.appendChild(icon(yes ? "check_circle" : "cancel"));
        flag.appendChild(el("span", "", yes ? t("Yes") : t("No")));
        wrapper.appendChild(flag);
        break;
      case "choice":
        wrapper.appendChild(el("span", "badge", entry.display));
        break;
      case "link":
      case "url":
      case "file":
        wrapper.appendChild(link(entry.url, entry.display));
        break;
      case "email":
        wrapper.appendChild(link("mailto:" + entry.display, entry.display));
        break;
      case "links":
        (entry.items || []).forEach(function (item, index) {
          if (index) {
            wrapper.appendChild(document.createTextNode(", "));
          }
          wrapper.appendChild(link(item.url, item.label));
        });
        break;
      case "tags":
        (entry.items || []).forEach(function (item) {
          wrapper.appendChild(tag(item));
        });
        break;
      default:
        wrapper.textContent = entry.display === undefined ? "" : String(entry.display);
    }

    if (entry.more) {
      wrapper.appendChild(el("span", "muted", " +" + entry.more));
    }

    return wrapper;
  }

  /* -- The tree --------------------------------------------------------- */

  function TreeView(element, config) {
    this.element = element;
    this.config = config;
    this.columns = config.columns || [];
    this.pageSize = config.pageSize || 50;
    this.top = this.node({ id: config.root ? null : config.node, depth: -1 });
    this.top.path = [];
    this.build();
  }

  TreeView.prototype.node = function (data) {
    return {
      key: data.key || data.id,
      id: data.id,
      label: data.label || "",
      url: data.url || "",
      linkUrl: data.linkUrl || "",
      count: data.children || 0,
      cycle: Boolean(data.cycle),
      cells: data.cells || [],
      depth: data.depth,
      path: [],
      expanded: false,
      loaded: false,
      loading: false,
      failed: false,
      items: [],
      total: 0,
      q: "",
      match: Boolean(data.match),
      partial: false,
      row: null,
      foot: null
    };
  };

  TreeView.prototype.build = function () {
    var self = this;
    var toolbar = el("div", "tree__toolbar");
    var status = el("span", "tree__status muted");
    var collapse = el("button", "button button--sm button--ghost");
    var refresh = el("button", "button button--sm button--ghost");
    var finder = el("label", "tree__find");
    var find = el("input", "input input--sm");

    // Every level at once, from the server: the branches leading to
    // what matches come back unfolded.
    find.type = "search";
    find.placeholder = t("Find at any depth");
    find.setAttribute("aria-label", t("Find at any depth"));
    find.addEventListener(
      "input",
      Generic.debounce(function () {
        self.find(find.value.trim());
      }, 400)
    );
    finder.appendChild(icon("manage_search", "muted"));
    finder.appendChild(find);

    collapse.type = "button";
    collapse.appendChild(icon("unfold_less"));
    collapse.appendChild(el("span", "", t("Collapse all")));
    collapse.addEventListener("click", function () {
      self.collapseAll();
    });

    refresh.type = "button";
    refresh.appendChild(icon("refresh"));
    refresh.appendChild(el("span", "", t("Refresh")));
    refresh.addEventListener("click", function () {
      self.reload();
    });

    toolbar.appendChild(finder);
    toolbar.appendChild(status);
    toolbar.appendChild(collapse);
    toolbar.appendChild(refresh);

    var scroller = el("div", "tree__scroll");
    var table = el("table", "tree-table");
    var head = el("thead");
    var headRow = el("tr");

    table.setAttribute("role", "treegrid");
    table.setAttribute("aria-label", this.config.label || t("Tree"));

    headRow.appendChild(el("th", "tree-table__label", this.config.label || ""));
    this.headings = this.columns.map(function (column) {
      var cell = el("th", "", column.label);

      cell.setAttribute("data-key", column.key);
      headRow.appendChild(cell);

      return cell;
    });
    headRow.appendChild(el("th", "tree-table__tools"));
    head.appendChild(headRow);

    this.body = el("tbody");
    this.body.addEventListener("keydown", function (event) {
      self.keydown(event);
    });

    table.appendChild(head);
    table.appendChild(this.body);
    scroller.appendChild(table);

    this.status = status;
    this.element.textContent = "";
    this.element.appendChild(toolbar);
    this.element.appendChild(scroller);
  };

  Object.defineProperty(TreeView.prototype, "width", {
    get: function () {
      return this.columns.length + 2;
    }
  });

  /** Ask for one page of what `parent` holds. */
  TreeView.prototype.fetch = function (parent, offset, limit) {
    var config = this.config;
    var params = {
      direction: config.direction || "down",
      offset: offset,
      limit: limit || this.pageSize,
      q: parent.q,
      path: parent.path.join(",")
    };

    if (parent === this.top && config.root) {
      params.root = config.root;
    } else if (parent.id !== null && parent.id !== undefined) {
      params.node = parent.id;
    }

    return Generic.api.get(config.url, params);
  };

  /** Fill `parent` with the page asked for: replaced, or added to. */
  TreeView.prototype.load = function (parent, append) {
    var self = this;
    var offset = append ? parent.items.length : 0;

    parent.loading = true;
    parent.failed = false;
    this.redraw(parent);

    return this.fetch(parent, offset)
      .then(function (answer) {
        var path = parent === self.top ? [] : parent.path.concat([parent.id]);
        var known = {};

        if (!append) {
          parent.items.forEach(function (child) {
            known[child.key] = child;
          });
          parent.items = [];
        }

        (answer.items || []).forEach(function (data) {
          var child = self.node(Object.assign({}, data, { depth: parent.depth + 1 }));
          var before = known[child.key];

          child.path = path;

          // Found again after a refresh: it stays open, its rows kept.
          if (before && before.expanded && child.count) {
            child.expanded = true;
            child.loaded = before.loaded;
            child.items = before.items;
            child.total = before.total;
            child.q = before.q;
            child.head = before.head;
            child.search = before.search;
          }

          parent.items.push(child);
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
        parent.loading = false;
        parent.failed = true;
        self.redraw(parent);

        if (error && error.status !== 404) {
          Generic.toast((error && error.message) || t("The tree could not be loaded."), "error");
        }
      });
  };

  /** The counts of the first level, for the tab and the status line. */
  TreeView.prototype.announce = function () {
    var top = this.top;
    var first = top.items[0];

    // Figures line up on the right, their headings with them.
    if (first) {
      this.headings.forEach(function (cell, index) {
        cell.classList.toggle("tree-row__number", (first.cells[index] || {}).type === "number");
      });
    }

    this.status.textContent = top.total
      ? Generic.format(Generic.nt("%(count)s record", "%(count)s records", top.total), { count: number(top.total) })
      : "";

    this.element.dispatchEvent(
      new window.CustomEvent("generic:tree-loaded", {
        bubbles: true,
        detail: { total: top.total, name: this.config.name }
      })
    );
  };

  TreeView.prototype.start = function () {
    var self = this;

    this.top.expanded = true;
    this.load(this.top, false).then(function () {
      // The one record a page is shown from: opened at once.
      if (self.config.root && self.top.items.length === 1) {
        self.toggle(self.top.items[0], true);
      }
    });
    this.follow();
  };

  /* -- Finding at any depth ------------------------------------------- */

  /** Ask for what matches `term` below the top, at any depth; under two
   * letters, back to the tree as it was. */
  TreeView.prototype.find = function (term) {
    var self = this;
    var config = this.config;

    if (!term || term.length < 2) {
      this.asking = null;

      if (this.found) {
        this.leaveFind();
      }

      return Promise.resolve();
    }

    var params = { direction: config.direction || "down", find: term };
    var asked = {};

    if (config.root) {
      params.root = config.root;
    } else if (config.node !== null && config.node !== undefined) {
      params.node = config.node;
    }

    this.term = term;
    this.asking = asked;
    this.status.textContent = t("Searching\u2026");

    return Generic.api
      .get(config.url, params)
      .then(function (answer) {
        // Typed further meanwhile: that search answers instead.
        if (self.asking === asked) {
          self.showFound(answer);
        }
      })
      .catch(function (error) {
        if (self.asking === asked) {
          self.status.textContent = "";
          Generic.toast((error && error.message) || t("The tree could not be loaded."), "error");
        }
      });
  };

  /** Draw a search's answer in place of the tree, kept aside. */
  TreeView.prototype.showFound = function (answer) {
    var top = this.node({ id: null, depth: -1 });

    if (!this.found) {
      this.normal = this.top;
    }

    top.path = [];
    top.expanded = true;
    top.loaded = true;
    top.items = this.foundItems(answer.items || [], top, []);
    top.total = top.items.length;
    this.found = true;
    this.top = top;
    this.redraw(top);

    var status = answer.matches
      ? Generic.format(Generic.nt("%(count)s match", "%(count)s matches", answer.matches), { count: number(answer.matches) })
      : t("Nothing matches.");

    if (answer.truncated) {
      status += " " + t("(the first ones only: be more precise)");
    }

    this.status.textContent = status;
  };

  TreeView.prototype.foundItems = function (list, parent, path) {
    var self = this;

    return list.map(function (data) {
      var child = self.node(Object.assign({}, data, { depth: parent.depth + 1 }));

      child.path = path;

      if (data.items) {
        child.expanded = true;
        child.loaded = true;
        child.partial = true;
        child.items = self.foundItems(data.items, child, path.concat([child.id]));
        child.total = child.items.length;
      }

      return child;
    });
  };

  /** The search box emptied: the tree as it was left. */
  TreeView.prototype.leaveFind = function () {
    this.found = false;
    this.top = this.normal;
    this.redraw(this.top);
    this.announce();
  };

  /* -- Rows ------------------------------------------------------------- */

  TreeView.prototype.rowOf = function (node) {
    if (node.row) {
      this.updateRow(node);
      return node.row;
    }

    var self = this;
    var row = el("tr", "tree-row" + (node.match ? " is-match" : ""));
    var first = el("td", "tree-row__label");
    var inner = el("div", "tree-row__inner");
    var toggle = el("button", "tree-row__toggle");
    var tools = el("td", "tree-table__tools");

    row.setAttribute("role", "row");
    row.setAttribute("aria-level", String(node.depth + 1));
    row.setAttribute("data-depth", String(node.depth));
    row.tabIndex = -1;
    row.treeNode = node;

    inner.style.paddingInlineStart = node.depth * 1.25 + "rem";
    toggle.type = "button";
    toggle.tabIndex = -1;
    toggle.addEventListener("click", function () {
      self.toggle(node);
    });
    inner.appendChild(toggle);

    var label = link(node.url, node.label);

    label.className = "tree-row__name";
    label.tabIndex = -1;
    inner.appendChild(label);

    if (node.cycle) {
      var loop = icon("sync_problem", "tree-row__cycle");

      loop.removeAttribute("aria-hidden");
      loop.setAttribute("role", "img");
      loop.title = t("Already above in this branch: not unfolded again.");
      loop.setAttribute("aria-label", loop.title);
      inner.appendChild(loop);
    }

    var count = el("span", "tree-row__count");

    inner.appendChild(count);
    first.appendChild(inner);
    row.appendChild(first);

    this.columns.forEach(function (column, index) {
      var entry = node.cells[index] || { empty: true };
      var cell = el("td", entry.type === "number" ? "tree-row__number" : "");

      cell.appendChild(value(entry));
      row.appendChild(cell);
    });

    if (node.linkUrl && Generic.isSafeUrl(node.linkUrl)) {
      var edit = el("a", "icon-button icon-button--sm");

      edit.href = node.linkUrl;
      edit.title = t("Edit the link");
      edit.setAttribute("aria-label", edit.title);
      edit.tabIndex = -1;
      edit.appendChild(icon("edit"));
      tools.appendChild(edit);
    }

    row.appendChild(tools);
    row.addEventListener("click", function (event) {
      if (event.target === row || event.target.tagName === "TD") {
        self.focus(row);
      }
    });

    node.row = row;
    node.toggleButton = toggle;
    node.countBadge = count;
    this.updateRow(node);

    return row;
  };

  TreeView.prototype.updateRow = function (node) {
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
    } else {
      toggle.removeAttribute("aria-label");
    }

    if (expandable) {
      node.row.setAttribute("aria-expanded", node.expanded ? "true" : "false");
      node.countBadge.textContent = number(node.count);
      node.countBadge.hidden = false;
    } else {
      node.row.removeAttribute("aria-expanded");
      node.countBadge.hidden = true;
    }
  };

  /** A row spanning the table at the level below `parent`. */
  TreeView.prototype.levelRow = function (parent, className) {
    var row = el("tr", "tree-row " + className);
    var cell = el("td");
    var inner = el("div", "tree-row__inner tree-foot");

    row.setAttribute("data-depth", String(parent.depth + 1));
    cell.colSpan = this.width;
    inner.style.paddingInlineStart = (parent.depth + 1) * 1.25 + "rem";
    cell.appendChild(inner);
    row.appendChild(cell);
    row.inner = inner;

    return row;
  };

  /** A level holding more than a page gets a search box, first.
   *
   * Kept for as long as the level is searchable: drawing the rows
   * again below it leaves it in place, focused, with what was typed.
   */
  TreeView.prototype.headOf = function (parent) {
    var self = this;

    if (!(parent.total > this.pageSize || parent.q)) {
      return null;
    }

    if (!parent.head) {
      var row = this.levelRow(parent, "tree-row--head");
      var search = el("input", "input input--sm tree-foot__search");

      search.type = "search";
      search.setAttribute("aria-label", t("Search this level"));
      search.addEventListener(
        "input",
        Generic.debounce(function () {
          parent.q = search.value.trim();
          self.load(parent, false);
        }, 350)
      );
      row.inner.appendChild(icon("search", "muted"));
      row.inner.appendChild(search);
      parent.head = row;
      parent.search = search;
    }

    if (!parent.q) {
      parent.search.placeholder = Generic.format(t("Search these %(count)s"), {
        count: number(parent.total)
      });
    }

    return parent.head;
  };

  /** The row closing a level: loading, failed, more to show. */
  TreeView.prototype.footOf = function (parent) {
    var self = this;
    var shown = parent.items.length;
    var more = parent.total - shown;
    var hidden = parent.partial ? parent.count - shown : 0;

    if (!parent.loading && !parent.failed && more <= 0 && hidden <= 0 && shown) {
      return null;
    }

    var row = this.levelRow(parent, "tree-row--foot");
    var rest = row.inner;

    if (hidden > 0 && !parent.loading && !parent.failed) {
      // Found: only what leads to a match is shown of this level.
      var all = el("button", "button button--sm button--ghost");

      all.type = "button";
      all.appendChild(icon("unfold_more"));
      all.appendChild(el("span", "", t("Show them all")));
      all.addEventListener("click", function () {
        parent.partial = false;
        self.load(parent, false);
      });
      rest.appendChild(
        el(
          "span",
          "muted",
          Generic.format(Generic.nt("%(count)s more, not matching", "%(count)s more, not matching", hidden), { count: number(hidden) })
        )
      );
      rest.appendChild(all);
    } else if (parent.loading) {
      rest.appendChild(icon("progress_activity", "tree-row__spin"));
      rest.appendChild(el("span", "muted", t("Loading\u2026")));
    } else if (parent.failed) {
      var retry = el("button", "button button--sm button--ghost", t("Try again"));

      retry.type = "button";
      retry.addEventListener("click", function () {
        self.load(parent, false);
      });
      rest.appendChild(el("span", "muted", t("This level could not be loaded.")));
      rest.appendChild(retry);
    } else if (!shown) {
      rest.appendChild(el("span", "muted", parent.q ? t("Nothing matches.") : t("Nothing here.")));
    } else {
      var next = el("button", "button button--sm");

      next.type = "button";
      next.appendChild(icon("expand_more"));
      next.appendChild(el("span", "", Generic.format(t("Show %(count)s more"), { count: number(Math.min(more, self.pageSize)) })));
      next.addEventListener("click", function () {
        self.load(parent, true);
      });
      rest.appendChild(el("span", "muted", Generic.format(t("%(shown)s of %(total)s"), { shown: number(shown), total: number(parent.total) })));
      rest.appendChild(next);
    }

    return row;
  };

  /** Every row below `parent`, in order, as it should be drawn now. */
  TreeView.prototype.rowsBelow = function (parent) {
    var self = this;
    var rows = [];

    if (!parent.expanded) {
      return rows;
    }

    var head = this.headOf(parent);

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
   * deeper level. Its search row, if it has one, stays in the page. */
  TreeView.prototype.redraw = function (parent) {
    var body = this.body;
    var head = parent.head;
    var fragment = document.createDocumentFragment();
    var stale = [];
    var next;

    if (parent.row) {
      this.updateRow(parent);
    }

    if (parent === this.top) {
      stale = Array.prototype.slice.call(body.children);
    } else if (parent.row.parentNode) {
      next = parent.row.nextElementSibling;

      while (next && Number(next.getAttribute("data-depth")) > parent.depth) {
        stale.push(next);
        next = next.nextElementSibling;
      }
    } else {
      return;
    }

    stale.forEach(function (row) {
      if (row !== head) {
        body.removeChild(row);
      }
    });

    var rows = this.rowsBelow(parent);
    var kept = Boolean(head && head.parentNode && rows[0] === head);

    if (head && head.parentNode && !kept) {
      body.removeChild(head);
    }

    rows.forEach(function (row) {
      if (!(kept && row === head)) {
        fragment.appendChild(row);
      }
    });

    if (kept) {
      body.insertBefore(fragment, head.nextSibling);
    } else if (parent === this.top) {
      body.insertBefore(fragment, body.firstChild);
    } else {
      body.insertBefore(fragment, parent.row.nextSibling);
    }

    if (!body.querySelector('tr[tabindex="0"]')) {
      var first = body.querySelector("tr.tree-row:not(.tree-row--foot):not(.tree-row--head)");

      if (first) {
        first.tabIndex = 0;
      }
    }
  };

  TreeView.prototype.toggle = function (node, open) {
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

  TreeView.prototype.collapseAll = function () {
    var self = this;

    this.top.items.forEach(function (node) {
      self.forEach(node, function (child) {
        child.expanded = false;
      });
    });
    this.redraw(this.top);
  };

  TreeView.prototype.forEach = function (node, callback) {
    var self = this;

    callback(node);
    node.items.forEach(function (child) {
      self.forEach(child, callback);
    });
  };

  /** Load again every level that is open, keeping it open. */
  TreeView.prototype.reload = function () {
    var self = this;
    var open = [];

    if (this.found) {
      return this.find(this.term);
    }

    function walk(node) {
      if (node.expanded && node.loaded) {
        open.push(node);
        node.items.forEach(walk);
      }
    }

    walk(this.top);

    // Top down: a level's children are matched again by their key.
    return open.reduce(function (chain, node) {
      return chain.then(function () {
        if (node !== self.top && !self.isShown(node)) {
          return null;
        }

        return self.reloadLevel(node);
      });
    }, Promise.resolve());
  };

  TreeView.prototype.isShown = function (node) {
    return Boolean(node.row && node.row.parentNode);
  };

  TreeView.prototype.reloadLevel = function (node) {
    var self = this;
    var wanted = Math.min(500, Math.max(this.pageSize, node.items.length));

    return this.fetch(node, 0, wanted)
      .then(function (answer) {
        var known = {};

        node.items.forEach(function (child) {
          known[child.key] = child;
        });

        node.items = (answer.items || []).map(function (data) {
          var fresh = self.node(Object.assign({}, data, { depth: node.depth + 1 }));
          var before = known[fresh.key];

          fresh.path = node === self.top ? [] : node.path.concat([node.id]);

          if (before && before.expanded && fresh.count) {
            fresh.expanded = true;
            fresh.loaded = before.loaded;
            fresh.items = before.items;
            fresh.total = before.total;
            fresh.q = before.q;
            fresh.head = before.head;
            fresh.search = before.search;
          }

          return fresh;
        });
        node.total = answer.total || 0;

        if (node === self.top) {
          self.announce();
        }

        self.redraw(node);
      })
      .catch(function () {
        /* What is shown stays; the next change tries again. */
      });
  };

  /** Load again when a record, or a link, of this tree changes. */
  TreeView.prototype.follow = function () {
    var self = this;
    var resources = this.config.resources || [];

    if (!Generic.events || !(this.config.topics || []).length) {
      return;
    }

    var reload = Generic.debounce(function () {
      self.reload();
    }, 600);

    this.config.topics.forEach(function (topic) {
      Generic.events.subscribe(topic);
    });
    Generic.events.on("resource.changed", function (payload) {
      if (payload && payload.resource && resources.indexOf(payload.resource) === -1) {
        return;
      }

      if (document.body.contains(self.element)) {
        reload();
      }
    });
  };

  /* -- The keyboard: a treegrid's ---------------------------------------- */

  TreeView.prototype.rows = function () {
    return Array.prototype.slice.call(this.body.querySelectorAll("tr.tree-row:not(.tree-row--foot):not(.tree-row--head)"));
  };

  TreeView.prototype.focus = function (row) {
    if (!row) {
      return;
    }

    this.rows().forEach(function (other) {
      other.tabIndex = other === row ? 0 : -1;
    });
    row.focus();
  };

  TreeView.prototype.keydown = function (event) {
    var row = event.target;

    if (!row || row.tagName !== "TR" || !row.treeNode) {
      return;
    }

    var node = row.treeNode;
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
          this.focus(node.items[0].row);
        }
        break;
      case "ArrowLeft":
        if (node.expanded) {
          this.toggle(node, false);
        } else {
          var parent = rows
            .slice(0, index)
            .reverse()
            .find(function (other) {
              return other.treeNode.depth < node.depth;
            });

          this.focus(parent);
        }
        break;
      case "Enter":
        if (node.url && Generic.isSafeUrl(node.url)) {
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

  /* -- Starting ----------------------------------------------------------- */

  function start(element) {
    if (!element || element.genericTree) {
      return element && element.genericTree;
    }

    var config = readJson(element.getAttribute("data-config"));

    if (!config || !config.url) {
      return null;
    }

    var view = new TreeView(element, config);

    element.genericTree = view;
    view.start();

    return view;
  }

  Generic.tree = { start: start, value: value };

  Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".generic-tree[data-autostart]"), start);
  });
})(window, document);

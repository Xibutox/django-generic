/**
 * The table controller.
 *
 * Owns one DataTables instance: builds its options, carries its state -
 * visible columns, sorting, filters, search, page length - and hands it
 * to the features that extend it: the toolbar, the filter bar, row
 * selection and bulk actions, the row menu, live refresh. See
 * `registerFeature` in core.js.
 *
 * The filters are a tree held here, not controls in the page
 * (query.js): the filter bar draws it and edits it through
 * `setFilters`, `addCondition` and friends. They are part of the saved
 * state, so a table comes back the way it was left, and a whole layout
 * can be captured under a name and applied again later.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var columnsModule = namespace.columns;
  var query = namespace.query;
  var t = core.t;

  //: Query parameters a table page may be opened with.
  var URL_FILTERS = "filters";
  var URL_SEARCH = "search";

  function GenericDataTable(table, suppliedOptions) {
    var self = this;

    suppliedOptions = suppliedOptions || {};

    this.table = table;
    this.url = suppliedOptions.url || table.dataset.url;

    if (!this.url) {
      throw new Error(t("A data source URL is required."));
    }

    var contextOptions = core.readJsonScript(table.dataset.optionsId, {});

    this.options = Object.assign(
      {},
      core.DEFAULTS,
      contextOptions,
      suppliedOptions
    );

    this.options.language = Object.assign(
      {},
      core.language(),
      contextOptions.language || {},
      suppliedOptions.language || {}
    );

    this.columns = columnsModule.normalizeColumns(
      suppliedOptions.columns ||
        core.readJsonScript(table.dataset.columnsId, [])
    );

    if (!this.columns.length) {
      throw new Error(t("No columns were configured."));
    }

    this.listeners = [];
    this.slots = {};
    this.batching = false;
    this.restoredState = false;
    this.filterTree = query.emptyTree();
    this.linkState = this.options.syncUrl ? this.readLink() : null;

    if (this.linkState) {
      this.filterTree = query.normalize(this.linkState.filters, this.columns);
      this.restoredState = true;
    }

    this.features = core.featureRegistry.filter(function (feature) {
      return typeof feature.enabled !== "function" || feature.enabled(self);
    });

    // Features may add columns - the checkboxes, the row menu - so the
    // header and the signature are computed after they have.
    this.callFeatures("prepare");

    this.defaultVisibility = this.columns.map(function (column) {
      return column.visible !== false;
    });

    // A saved state built against a different set of columns would
    // restore the wrong widths and visibility.
    this.columnsSignature = this.columns
      .map(function (column) {
        return (
          (column.synthetic || column.data) +
          ":" +
          (column.visible !== false ? 1 : 0)
        );
      })
      .join("|");

    buildHeader(table, this.columns);

    // Before DataTables reads the header: a row it knows about is hidden
    // and shown with its column, one added later would fall out of step.
    this.callFeatures("header", table.tHead);

    this.instance = new window.DataTable(table, this.buildOptions());

    this.callFeatures("init");
    this.watchScrollBox();

    table.dispatchEvent(
      new CustomEvent("generic:datatable-ready", {
        bubbles: true,
        detail: { api: this.instance, controller: this }
      })
    );
  }

  /**
   * The header: a row of titles. A column added by a feature may
   * bring its own header node - the select-all checkbox, for instance.
   * The filter bar adds its buttons to these cells once DataTables has
   * laid them out; the filter row adds a row of its own below.
   */
  function buildHeader(table, columns) {
    var thead = table.tHead || table.createTHead();

    thead.replaceChildren();

    var titleRow = thead.insertRow();
    titleRow.className = "dt-column-titles";

    columns.forEach(function (column) {
      var cell = document.createElement("th");
      cell.scope = "col";

      if (column.headerNode) {
        cell.appendChild(column.headerNode);
      } else {
        cell.textContent = column.title;
        cell.title = column.title;
      }

      if (column.synthetic) {
        cell.className = column.className || "";
      }

      titleRow.appendChild(cell);
    });
  }

  /* -- The box the table scrolls in -------------------------------------
   *
   * A table wider than its card scrolls sideways inside it. One that
   * is wider by a fraction of a pixel - text that cannot wrap, columns
   * that just fail to fit - drew a scrollbar that scrolled nothing, and
   * whether it did depended on the window's width to the pixel. Under
   * two pixels the box clips instead; it scrolls again as soon as
   * something is really cut. Checked after every draw, when columns
   * are shown or hidden, and whenever the box changes width.
   */

  var SCROLL_SLACK = 2;

  GenericDataTable.prototype.fitScrollBox = function () {
    var box = this.table.parentElement;

    if (!box) {
      return;
    }

    box.classList.remove("dt-scroll-clipped");

    var overflow = box.scrollWidth - box.clientWidth;

    box.classList.toggle(
      "dt-scroll-clipped",
      overflow > 0 && overflow < SCROLL_SLACK
    );
  };

  GenericDataTable.prototype.watchScrollBox = function () {
    var self = this;
    var fit = function () {
      self.fitScrollBox();
    };

    this.instance.on("draw.dt.fit column-visibility.dt.fit", fit);

    if (window.ResizeObserver && this.table.parentElement) {
      this.scrollObserver = new window.ResizeObserver(core.debounce(fit, 100));
      this.scrollObserver.observe(this.table.parentElement);
    } else {
      this.listen(window, "resize", core.debounce(fit, 100));
    }

    fit();
  };

  /* -- Plumbing -------------------------------------------------------
   *
   * Every listener attached outside the table itself is recorded, so
   * destroy() can take them all off again. Without this a page that
   * rebuilds its tables leaks a scroll and resize handler per draw.
   */

  GenericDataTable.prototype.listen = function (target, type, handler, options) {
    target.addEventListener(type, handler, options);
    this.listeners.push([target, type, handler, options]);
  };

  /** Call `method` on every feature defining it: (controller, ...rest). */
  GenericDataTable.prototype.callFeatures = function (method) {
    var args = [this].concat(Array.prototype.slice.call(arguments, 1));

    this.features.forEach(function (feature) {
      if (typeof feature[method] === "function") {
        feature[method].apply(feature, args);
      }
    });
  };

  /** The declared columns with their index, without the added ones. */
  GenericDataTable.prototype.dataColumns = function () {
    return this.columns
      .map(function (column, index) {
        return { column: column, index: index };
      })
      .filter(function (entry) {
        return !entry.column.synthetic;
      });
  };

  GenericDataTable.prototype.columnIndex = function (name) {
    for (var index = 0; index < this.columns.length; index += 1) {
      var column = this.columns[index];

      if (!column.synthetic && column.data === name) {
        return index;
      }
    }

    return -1;
  };

  /* -- DataTables options --------------------------------------------- */

  GenericDataTable.prototype.buildOptions = function () {
    var self = this;
    var userAjax = this.options.ajax || {};
    var userData = userAjax.data;

    var options = {
      processing: true,
      serverSide: true,
      deferRender: true,
      autoWidth: false,
      stateSave: this.options.stateSave,
      // Kept until the user changes it, not for two hours.
      stateDuration: 0,
      searchDelay: this.options.searchDelay,
      pageLength: this.options.pageLength,
      lengthMenu: this.options.lengthMenu,
      columns: this.columns.map(columnsModule.toDataTablesColumn),
      order: this.options.order || [],
      language: this.options.language,
      orderCellsTop: true,
      // The titles and the sorting belong to the first row, whatever
      // rows the features add under it.
      titleRow: 0,

      stateSaveParams: function (settings, data) {
        data.genericColumnsSignature = self.columnsSignature;
        data.genericFilterTree = self.collectFilters(true);
        delete data.genericFilters;
        self.callFeatures("saveState", data);
      },

      stateLoadParams: function (settings, data) {
        self.callFeatures("loadState", data);

        if (data.genericColumnsSignature !== self.columnsSignature) {
          // The columns changed since this state was saved; keep the
          // rest of it but let the new declaration decide the columns.
          delete data.columns;
          delete data.order;
        }

        // A link says what to show; it wins over what was left.
        if (self.linkState) {
          if (data.search) {
            data.search.search = self.linkState.search || "";
          }

          return;
        }

        self.restoredState = true;

        // Called before the first request: the tree is in place when
        // that request is built. The older state kept a flat payload.
        var stored = data.genericFilterTree || data.genericFilters;

        if (stored) {
          self.filterTree = query.normalize(stored, self.columns);
        }
      },

      layout: this.options.layout || {
        top: function () {
          return self.buildTop();
        },
        topStart: null,
        topEnd: null,
        bottomStart: ["pageLength", "info"],
        bottomEnd: "paging"
      },

      ajax: Object.assign({}, userAjax, {
        url: this.url,
        type: userAjax.type || "GET",
        data: function (requestData) {
          requestData.format = "datatables";

          var filters = self.collectFilters();

          if (filters) {
            requestData.filters = JSON.stringify(filters);
          }

          Object.assign(
            requestData,
            core.resolveExtraParams(self.options, self.table)
          );

          if (typeof userData === "function") {
            var result = userData(requestData, self.table);
            return result === undefined || result === null
              ? requestData
              : result;
          }

          if (userData && typeof userData === "object") {
            Object.assign(requestData, userData);
          }

          return requestData;
        },
        error: function (xhr) {
          self.reportAjaxError(xhr);
        }
      })
    };

    if (this.linkState && this.linkState.search) {
      options.search = { search: this.linkState.search };
    }

    if (this.options.stateKey) {
      var storageKey = "GenericDataTable_" + this.options.stateKey;

      options.stateSaveCallback = function (settings, data) {
        try {
          window.localStorage.setItem(storageKey, JSON.stringify(data));
        } catch (error) {
          /* Private mode: the layout simply is not remembered. */
        }
      };

      options.stateLoadCallback = function () {
        try {
          return JSON.parse(window.localStorage.getItem(storageKey));
        } catch (error) {
          return null;
        }
      };
    }

    return options;
  };

  /** The band above the table, assembled from the features. */
  GenericDataTable.prototype.buildTop = function () {
    var self = this;
    var top = core.el("div", "dt-top");

    this.features.forEach(function (feature) {
      if (typeof feature.top === "function") {
        var node = feature.top(self);

        if (node) {
          top.appendChild(node);
        }
      }
    });

    return top;
  };

  /**
   * Surface a rejected request instead of leaving an empty table.
   *
   * The server answers a bad filter with `{"error": "..."}` under
   * `?format=datatables`; without this the user sees no rows and no
   * reason why.
   */
  GenericDataTable.prototype.reportAjaxError = function (xhr) {
    var message = t("The table could not be loaded.");

    try {
      var payload = JSON.parse(xhr.responseText);

      if (payload && payload.error) {
        message = payload.error;
      }
    } catch (error) {
      /* Not JSON: keep the generic message. */
    }

    this.table.dispatchEvent(
      new CustomEvent("generic:datatable-error", {
        bubbles: true,
        detail: { message: message, xhr: xhr }
      })
    );
  };

  /* -- Links ------------------------------------------------------------
   *
   * With `syncUrl`, the address says what the table shows: the filters
   * and the search travel in it, so a filtered table can be bookmarked,
   * shared, and reached again with the back button.
   */

  GenericDataTable.prototype.readLink = function () {
    var params = new URLSearchParams(window.location.search);
    var raw = params.get(URL_FILTERS);
    var search = params.get(URL_SEARCH);

    if (!raw && !search) {
      return null;
    }

    var filters = null;

    try {
      filters = raw ? JSON.parse(raw) : null;
    } catch (error) {
      filters = null;
    }

    return { filters: filters, search: search || "" };
  };

  GenericDataTable.prototype.writeLink = function () {
    if (!this.options.syncUrl || !window.history || !window.history.replaceState) {
      return;
    }

    var url = new URL(window.location.href);
    var tree = this.collectFilters(true);
    var search = this.instance ? this.instance.search() : "";

    url.searchParams.delete(URL_FILTERS);
    url.searchParams.delete(URL_SEARCH);

    if (tree) {
      url.searchParams.set(URL_FILTERS, JSON.stringify(tree));
    }

    if (search) {
      url.searchParams.set(URL_SEARCH, search);
    }

    if (url.toString() !== window.location.href) {
      window.history.replaceState(window.history.state, "", url.toString());
    }
  };

  /* -- Filters ---------------------------------------------------------- */

  /**
   * The filter tree as the server reads it, or null when nothing
   * filters. `withLabels` keeps what a saved view needs to show the
   * values again - their labels - and incomplete conditions.
   */
  GenericDataTable.prototype.collectFilters = function (withLabels) {
    if (withLabels) {
      return this.filterTree.conditions.length ? query.forState(this.filterTree) : null;
    }

    return query.forRequest(this.filterTree, this.columns);
  };

  /**
   * Replace the filters: a tree, the older flat payload, or nothing.
   * The caller draws; `bound` is kept for the older signature.
   */
  GenericDataTable.prototype.setFilters = function (filters) {
    this.filterTree = query.normalize(filters, this.columns);
    this.filtersChanged(false);
  };

  /** Add a condition, to the top level or to a group of the tree. */
  GenericDataTable.prototype.addCondition = function (condition, groupId, redraw) {
    var group = this.filterTree;

    if (groupId) {
      var place = query.locate(this.filterTree, groupId);

      group = place && query.isGroup(place.node) ? place.node : this.filterTree;
    }

    condition.id = condition.id || query.uid();
    group.conditions.push(condition);
    this.filtersChanged(redraw);

    return condition;
  };

  /** Replace the conditions on one column with this one. */
  GenericDataTable.prototype.setColumnCondition = function (condition, redraw) {
    var tree = this.filterTree;

    query.conditionsOn(tree, condition.column).forEach(function (existing) {
      query.remove(tree, existing.id);
    });

    return this.addCondition(condition, null, redraw);
  };

  GenericDataTable.prototype.replaceCondition = function (id, condition, redraw) {
    var place = query.locate(this.filterTree, id);

    if (!place) {
      return this.addCondition(condition, null, redraw);
    }

    condition.id = id;
    place.group.conditions[place.index] = condition;
    this.filtersChanged(redraw);

    return condition;
  };

  GenericDataTable.prototype.removeCondition = function (id, redraw) {
    if (query.remove(this.filterTree, id)) {
      this.filtersChanged(redraw);
    }
  };

  /**
   * Tell the features the filters changed - the bar, the header, the
   * count, the address - and draw, unless `redraw` is false.
   */
  GenericDataTable.prototype.filtersChanged = function (redraw) {
    this.table.dispatchEvent(
      new CustomEvent("generic:filters-change", {
        bubbles: true,
        detail: { controller: this, tree: this.filterTree }
      })
    );

    this.writeLink();

    if (redraw !== false) {
      this.redraw();
    }
  };

  /** Empty every filter and the search box, without drawing. */
  GenericDataTable.prototype.clearFilters = function () {
    this.filterTree = query.emptyTree();

    if (this.instance) {
      this.instance.search("");
    }

    if (this.searchInput) {
      this.searchInput.value = "";
      this.searchInput.dispatchEvent(new CustomEvent("generic:sync"));
    }

    this.filtersChanged(false);
  };

  GenericDataTable.prototype.activeFilterCount = function () {
    var count = query.count(this.filterTree, this.columns);

    if (this.instance && this.instance.search()) {
      count += 1;
    }

    return count;
  };

  /**
   * The query parameters describing the rows currently shown: what an
   * export, a bulk action on "every row", a chart or a facet has to
   * repeat.
   */
  GenericDataTable.prototype.currentParams = function () {
    var params = {};
    var filters = this.collectFilters();

    if (filters) {
      params.filters = JSON.stringify(filters);
    }

    var search = this.instance ? this.instance.search() : "";

    if (search) {
      params.search = search;
    }

    Object.entries(core.resolveExtraParams(this.options, this.table)).forEach(
      function (entry) {
        if (entry[1] !== undefined && entry[1] !== null && entry[1] !== "") {
          params[entry[0]] = entry[1];
        }
      }
    );

    return params;
  };

  GenericDataTable.prototype.redraw = function () {
    // Several controls changed in one go - a saved view being applied -
    // make one request, not one each.
    if (this.batching || !this.instance) {
      return;
    }

    // Any filter change invalidates the current page number.
    this.instance.page("first");
    this.instance.draw(false);
  };

  GenericDataTable.prototype.reload = function (resetPaging) {
    this.instance.ajax.reload(null, Boolean(resetPaging));
  };

  /* -- Layouts ------------------------------------------------------------ */

  /** Everything needed to show the table the same way again. */
  GenericDataTable.prototype.captureState = function () {
    var self = this;
    var api = this.instance;

    return {
      columns: this.dataColumns()
        .filter(function (entry) {
          return api.column(entry.index).visible();
        })
        .map(function (entry) {
          return entry.column.data;
        }),
      order: api
        .order()
        .map(function (entry) {
          var index = Array.isArray(entry) ? entry[0] : entry.idx;
          var direction = Array.isArray(entry) ? entry[1] : entry.dir;
          var column = self.columns[index];

          return column && !column.synthetic ? [column.data, direction] : null;
        })
        .filter(Boolean),
      filters: this.collectFilters(true) || query.forState(query.emptyTree()),
      search: api.search() || "",
      pageLength: api.page.len()
    };
  };

  /**
   * Show the table as `state` describes. An empty state is the
   * declared default: every column as declared, no filter, the default
   * order and page length.
   */
  GenericDataTable.prototype.applyState = function (state) {
    var self = this;
    var api = this.instance;

    state = state || {};

    this.batching = true;

    var visible = Array.isArray(state.columns) && state.columns.length
      ? state.columns.map(String)
      : null;

    this.dataColumns().forEach(function (entry) {
      api
        .column(entry.index)
        .visible(
          visible
            ? visible.indexOf(entry.column.data) !== -1
            : self.defaultVisibility[entry.index],
          false
        );
    });

    api.columns.adjust();

    api.search(state.search || "");

    if (this.searchInput) {
      this.searchInput.value = state.search || "";
      this.searchInput.dispatchEvent(new CustomEvent("generic:sync"));
    }

    this.setFilters(state.filters || null);

    var order = Array.isArray(state.order)
      ? state.order
          .map(function (entry) {
            return [
              self.columnIndex(entry[0]),
              entry[1] === "desc" ? "desc" : "asc"
            ];
          })
          .filter(function (entry) {
            return entry[0] >= 0;
          })
      : this.options.order || [];

    api.order(order);
    api.page.len(Number(state.pageLength) || this.options.pageLength);

    this.batching = false;

    this.table.dispatchEvent(
      new CustomEvent("generic:datatable-state", {
        bubbles: true,
        detail: { controller: this }
      })
    );

    this.redraw();
  };

  /** Forget the saved layout and go back to the declared one. */
  GenericDataTable.prototype.resetLayout = function () {
    this.instance.state.clear();
    this.applyState({});
  };

  /* -- Export ---------------------------------------------------------- */

  /**
   * Send the current view to an export endpoint.
   *
   * Filters, the search, ordering, extra parameters and the visible
   * columns all travel with it, so the file matches what is on screen -
   * every matching row of it, not just the page.
   */
  GenericDataTable.prototype.download = function (action) {
    var self = this;

    var url = new URL(
      this.url.replace(/\/$/, "") + "/" + action + "/",
      window.location.origin
    );

    Object.entries(this.currentParams()).forEach(function (entry) {
      url.searchParams.set(entry[0], entry[1]);
    });

    var order = this.instance.order();

    if (order.length) {
      var first = order[0];
      var column = this.columns[Array.isArray(first) ? first[0] : first.idx];
      var direction = Array.isArray(first) ? first[1] : first.dir;

      // The public column name, not the ORM path: the server resolves
      // ordering through its own whitelist and rejects anything else.
      if (column && column.data && !column.synthetic) {
        url.searchParams.set(
          "ordering",
          direction === "desc" ? "-" + column.data : column.data
        );
      }
    }

    var visible = this.dataColumns()
      .filter(function (entry) {
        return (
          entry.column.exportable !== false &&
          self.instance.column(entry.index).visible()
        );
      })
      .map(function (entry) {
        return entry.column.data;
      });

    if (visible.length) {
      url.searchParams.set("columns", visible.join(","));
    }

    window.location.href = url.toString();
  };

  /** A cell as plain text: the label of a choice, a word for a boolean. */
  GenericDataTable.prototype.cellText = function (column, row) {
    var value = row[column.data];

    if (value === null || value === undefined) {
      return "";
    }

    if (column.displayType === "tags") {
      value = columnsModule.tagLabels(value);
    } else if (column.displayType === "icons") {
      value = columnsModule.iconLabels(value);
    } else if (column.choices && column.choices.length) {
      var labels = columnsModule.choiceLabels(column);

      if (Object.prototype.hasOwnProperty.call(labels, String(value))) {
        value = labels[String(value)];
      }
    } else if (typeof value === "boolean") {
      value = value ? t("Yes") : t("No");
    } else if (Array.isArray(value)) {
      value = value.join(", ");
    } else if (typeof value === "object") {
      value = JSON.stringify(value);
    }

    return String(value).replace(/[\t\r\n]+/g, " ");
  };

  GenericDataTable.prototype.visibleDataColumns = function () {
    var api = this.instance;

    return this.dataColumns().filter(function (entry) {
      return api.column(entry.index).visible();
    });
  };

  /** The rows on screen, tab separated, onto the clipboard. */
  GenericDataTable.prototype.copyPage = function () {
    var self = this;
    var Generic = window.Generic;
    var columns = this.visibleDataColumns();
    var rows = this.instance.rows({ page: "current" }).data().toArray();

    var lines = [
      columns
        .map(function (entry) {
          return entry.column.title;
        })
        .join("\t")
    ];

    rows.forEach(function (row) {
      lines.push(
        columns
          .map(function (entry) {
            return self.cellText(entry.column, row);
          })
          .join("\t")
      );
    });

    function report(ok) {
      if (!Generic) {
        return;
      }

      Generic.toast(
        ok
          ? core.format(t("%(count)s row(s) copied."), { count: rows.length })
          : t("The clipboard is not available here."),
        ok ? "success" : "error"
      );
    }

    if (!window.navigator.clipboard) {
      report(false);
      return;
    }

    window.navigator.clipboard.writeText(lines.join("\n")).then(
      function () {
        report(true);
      },
      function () {
        report(false);
      }
    );
  };

  /** The rows on screen, in a plain page the browser prints. */
  GenericDataTable.prototype.printPage = function () {
    var self = this;
    var columns = this.visibleDataColumns();
    var rows = this.instance.rows({ page: "current" }).data().toArray();
    var title = document.title;

    var html =
      "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>" +
      core.escapeHtml(title) +
      "</title><style>body{font:12px system-ui,sans-serif;margin:24px}" +
      "h1{font-size:16px}table{border-collapse:collapse;width:100%}" +
      "th,td{border:1px solid #ccc;padding:4px 6px;text-align:left}" +
      "th{background:#f3f4f6}</style></head><body><h1>" +
      core.escapeHtml(title) +
      "</h1><table><thead><tr>" +
      columns
        .map(function (entry) {
          return "<th>" + core.escapeHtml(entry.column.title) + "</th>";
        })
        .join("") +
      "</tr></thead><tbody>" +
      rows
        .map(function (row) {
          return (
            "<tr>" +
            columns
              .map(function (entry) {
                return "<td>" + core.escapeHtml(self.cellText(entry.column, row)) + "</td>";
              })
              .join("") +
            "</tr>"
          );
        })
        .join("") +
      "</tbody></table></body></html>";

    var popup = window.open("", "_blank");

    if (!popup) {
      return;
    }

    popup.document.open();
    popup.document.write(html);
    popup.document.close();
    popup.focus();
    popup.print();
  };

  /* -- Lifecycle -------------------------------------------------------- */

  GenericDataTable.prototype.destroy = function () {
    this.callFeatures("destroy");

    if (this.scrollObserver) {
      this.scrollObserver.disconnect();
      this.scrollObserver = null;
    }

    this.listeners.forEach(function (entry) {
      entry[0].removeEventListener(entry[1], entry[2], entry[3]);
    });
    this.listeners = [];

    this.instance.destroy();
    this.table.dataset.genericDatatableReady = "false";
  };

  namespace.GenericDataTable = GenericDataTable;
})(window, document);

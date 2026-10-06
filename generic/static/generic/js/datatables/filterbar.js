/**
 * The filters of a table, drawn and edited.
 *
 * Nothing takes room until something filters: the filters are chips in
 * a bar under the toolbar, and every way to add one opens the same
 * editor in a popover.
 *
 *   + Filter            in the toolbar: pick a column, then its editor
 *   the funnel          in each column header: that column's filter
 *   the search box      status:open  hours:>2  opened:30d  -tags:billing
 *   a right click       on a cell: "only this value", "anything but"
 *   the filter row      under the headers, on demand (filterrow.js)
 *
 * The editor fits the column: words, numbers and dates with their
 * operators and relative periods, a searchable list of the values a
 * choice or a relation holds - with how many rows hold each, from the
 * facets endpoint - and "is empty" everywhere. Conditions combine with
 * all or any, and a group of conditions may sit inside.
 *
 * The state lives in the controller (table.js) as a tree; this file only
 * draws it and calls `addCondition`, `replaceCondition`,
 * `removeCondition` and `filtersChanged`.
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var query = namespace.query;
  var columnsModule = namespace.columns;
  var el = core.el;
  var icon = core.icon;
  var t = core.t;

  var KIND_ICONS = {
    text: "text_fields",
    number: "numbers",
    date: "calendar_month",
    boolean: "toggle_on",
    multiselect: "checklist"
  };

  function generic() {
    return window.Generic || null;
  }

  function button(className, label, iconName) {
    var node = el("button", className);

    node.type = "button";

    if (iconName) {
      node.appendChild(icon(iconName, "icon--sm"));
    }

    if (label) {
      node.appendChild(el("span", "", label));
    }

    return node;
  }

  function formatCount(count) {
    try {
      return Number(count).toLocaleString(document.documentElement.lang || undefined);
    } catch (error) {
      return String(count);
    }
  }

  /* -- Popover ----------------------------------------------------------
   *
   * One floating panel per table, moved to the body so the table's own
   * scroll never clips it. A click outside or Escape closes it; the
   * page scrolling moves it with its anchor.
   */

  var openPopover = null;

  function Popover(controller) {
    var self = this;

    this.node = el("div", "dt-popover");
    this.node.hidden = true;
    this.node.setAttribute("role", "dialog");
    this.anchor = null;
    this.rect = null;

    document.body.appendChild(this.node);

    this.node.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        self.close(true);
      }
    });

    controller.listen(
      document,
      "mousedown",
      function (event) {
        if (self.node.hidden || self.node.contains(event.target)) {
          return;
        }

        if (self.anchor && self.anchor.contains && self.anchor.contains(event.target)) {
          return;
        }

        self.close(false);
      },
      true
    );

    controller.listen(window, "resize", function () {
      self.position();
    });

    controller.listen(
      window,
      "scroll",
      function (event) {
        if (!self.node.hidden && !self.node.contains(event.target)) {
          self.position();
        }
      },
      true
    );
  }

  Popover.prototype.open = function (anchor, content, label) {
    if (openPopover && openPopover !== this) {
      openPopover.close(false);
    }

    openPopover = this;
    this.anchor = anchor;
    this.node.replaceChildren(content);
    this.node.setAttribute("aria-label", label || "");
    this.node.hidden = false;
    this.position();

    var focus = this.node.querySelector("[data-autofocus]") ||
      this.node.querySelector("input, select, button");

    if (focus) {
      focus.focus({ preventScroll: true });
    }
  };

  Popover.prototype.isOpenFor = function (anchor) {
    return !this.node.hidden && this.anchor === anchor;
  };

  Popover.prototype.position = function () {
    if (this.node.hidden || !this.anchor) {
      return;
    }

    if (this.anchor.isConnected) {
      this.rect = this.anchor.getBoundingClientRect();
    }

    var rect = this.rect;

    if (!rect) {
      return;
    }

    var width = this.node.offsetWidth;
    var height = this.node.offsetHeight;
    var left = Math.min(rect.left, window.innerWidth - width - 8);
    var top = rect.bottom + 6;

    if (top + height > window.innerHeight - 8 && rect.top - height - 6 > 8) {
      top = rect.top - height - 6;
    }

    this.node.style.left = Math.max(8, left) + "px";
    this.node.style.top = Math.max(8, top) + "px";
  };

  Popover.prototype.close = function (restoreFocus) {
    if (this.node.hidden) {
      return;
    }

    this.node.hidden = true;
    this.node.replaceChildren();

    if (openPopover === this) {
      openPopover = null;
    }

    if (restoreFocus && this.anchor && this.anchor.isConnected && this.anchor.focus) {
      this.anchor.focus();
    }
  };

  Popover.prototype.destroy = function () {
    this.node.remove();
  };

  /* -- Values ------------------------------------------------------------
   *
   * What a column holds: the facets endpoint when the column offers it -
   * values present under the other filters, with their counts - else
   * its fixed choices, else its autocomplete route.
   */

  function facetsUrl(controller) {
    return controller.url.replace(/[?#].*$/, "").replace(/\/$/, "") + "/facets/";
  }

  function loadValues(controller, column, term, ids) {
    var Generic = generic();
    var key = query.keyOf(column);

    if (column.facets && !column.facetsFailed && Generic) {
      var params = Object.assign({}, controller.currentParams(), { column: key });

      if (term) {
        params.q = term;
      }

      if (ids && ids.length) {
        params.ids = ids.join(",");
      }

      return Generic.api.get(facetsUrl(controller), params).then(
        function (body) {
          if (body.kind === "range") {
            return { kind: "range", min: body.min, max: body.max, empty: body.empty || 0 };
          }

          var empty = 0;
          var values = (body.values || []).filter(function (entry) {
            if (entry.value === null || entry.value === "") {
              empty += entry.count || 0;
              return false;
            }

            return true;
          });

          return { kind: "values", values: values, more: Boolean(body.more), empty: empty };
        },
        function (error) {
          // A table without facets - an aggregated one - still works:
          // the editor falls back to what the column itself declares.
          if (error && (error.status === 400 || error.status === 404)) {
            column.facetsFailed = true;
            return loadValues(controller, column, term, ids);
          }

          throw error;
        }
      );
    }

    if (column.choices && column.choices.length) {
      var wanted = String(term || "").toLowerCase();

      return Promise.resolve({
        kind: "values",
        values: column.choices
          .filter(function (choice) {
            return !wanted || String(choice.label).toLowerCase().indexOf(wanted) !== -1;
          })
          .map(function (choice) {
            return { value: choice.value, label: choice.label };
          }),
        more: false,
        empty: 0
      });
    }

    if (column.autocompleteUrl && Generic) {
      var lookup = ids && ids.length ? { ids: ids.join(",") } : { q: term || "", page: 1 };

      return Generic.api.get(column.autocompleteUrl, lookup).then(function (body) {
        return {
          kind: "values",
          values: (body.results || []).map(function (row) {
            return { value: row.id, label: row.text };
          }),
          more: Boolean(body.pagination && body.pagination.more),
          empty: 0
        };
      });
    }

    return Promise.resolve({ kind: "values", values: [], more: false, empty: 0 });
  }

  /** A value as the list draws it: a coloured tag, or its label. */
  function valueNode(entry, column) {
    var node = el("span", "dt-value-label");

    if (entry.tag && columnsModule.tagHtml) {
      // tagHtml escapes the label and checks every colour.
      node.innerHTML = columnsModule.tagHtml(entry.tag, {});
    } else {
      node.textContent = entry.label;
    }

    return node;
  }

  /* -- Picking a column ------------------------------------------------------ */

  function openFieldPicker(controller, anchor, options) {
    options = options || {};

    var popover = controller.filterPopover;
    var root = el("div", "dt-picker");
    var search = el("input", "input input--sm dt-picker__search");
    var list = el("div", "dt-picker__list");
    var columns = query.filterable(controller.columns);

    search.type = "search";
    search.placeholder = t("Filter by") + "\u2026";
    search.setAttribute("aria-label", t("Find a column"));
    search.dataset.autofocus = "";
    list.setAttribute("role", "listbox");

    function choose(column) {
      openEditor(controller, anchor, {
        column: column,
        groupId: options.groupId,
        newGroup: options.newGroup,
        after: options.after
      });
    }

    function render() {
      list.replaceChildren();

      query.suggestColumns(controller.columns, search.value).forEach(function (column) {
        var item = el("button", "dt-picker__item");
        var filtered = query.conditionsOn(controller.filterTree, query.keyOf(column)).length;

        item.type = "button";
        item.setAttribute("role", "option");
        item.append(
          icon(KIND_ICONS[query.kind(column)] || "filter_alt", "icon--sm"),
          el("span", "dt-picker__label", column.title)
        );

        if (filtered) {
          item.appendChild(el("span", "dt-picker__badge", String(filtered)));
        }

        item.addEventListener("click", function () {
          choose(column);
        });

        list.appendChild(item);
      });

      if (!list.childNodes.length) {
        list.appendChild(el("div", "dt-picker__empty", t("No column matches.")));
      }
    }

    function move(step) {
      var items = Array.from(list.querySelectorAll(".dt-picker__item"));
      var index = items.indexOf(document.activeElement);

      if (!items.length) {
        return;
      }

      index = index === -1 ? (step > 0 ? 0 : items.length - 1) : index + step;

      if (index < 0) {
        search.focus();
        return;
      }

      items[Math.min(index, items.length - 1)].focus();
    }

    search.addEventListener("input", render);
    search.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        move(1);
      } else if (event.key === "Enter") {
        event.preventDefault();

        var first = list.querySelector(".dt-picker__item");

        if (first) {
          first.click();
        }
      }
    });
    list.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        move(event.key === "ArrowDown" ? 1 : -1);
      }
    });

    root.append(search, list);

    if (!options.groupId && !options.newGroup && controller.filterTree.conditions.length) {
      var group = button("dt-picker__footer-action", t("Add a group: any of several"), "account_tree");

      group.addEventListener("click", function () {
        openFieldPicker(controller, anchor, { newGroup: true });
      });

      root.appendChild(group);
    }

    if (options.newGroup) {
      root.insertBefore(
        el("p", "dt-picker__intro", t("A group matches when any of its conditions does. Its first condition:")),
        search
      );
    }

    // A column with values to pick makes the best example.
    var example = columns.find(function (column) {
      return query.kind(column) === "multiselect";
    }) || columns[0];

    if (example && controller.searchInput) {
      root.appendChild(
        el(
          "p",
          "dt-picker__hint",
          core.format(t("Tip: type %(example)s in the search box."), {
            example: query.keyOf(example) + ":\u2026"
          })
        )
      );
    }

    render();
    popover.open(anchor, root, t("Add a filter"));
  }

  /* -- Editing a condition ----------------------------------------------------- */

  function readNumber(input) {
    return input.value === "" ? "" : input.value;
  }

  /** Words, any of which may match: typed, or picked from the values. */
  function wordsEditor(controller, column, draft, hooks) {
    var node = el("div", "dt-values");
    var tokens = el("div", "dt-tokens");
    var input = el("input", "input input--sm");
    var suggestions = el("div", "dt-values__suggestions");
    var words = Array.isArray(draft.value)
      ? draft.value.slice()
      : draft.value
        ? [draft.value]
        : [];

    input.type = "text";
    input.placeholder = t("A word or a phrase");
    input.dataset.autofocus = "";
    input.setAttribute("aria-label", t("Value"));

    function split(text) {
      return String(text || "")
        .split(",")
        .map(function (part) {
          return part.trim();
        })
        .filter(Boolean);
    }

    // The words kept as tokens, and those still being typed: the filter
    // follows both.
    function sync() {
      draft.value = words.slice();

      split(input.value).forEach(function (part) {
        if (draft.value.indexOf(part) === -1) {
          draft.value.push(part);
        }
      });
    }

    function renderTokens() {
      tokens.replaceChildren();

      words.forEach(function (word, index) {
        var token = el("span", "dt-token");
        var remove = button("dt-token__remove", "", "close");

        remove.setAttribute("aria-label", core.format(t("Remove %(value)s"), { value: word }));
        remove.addEventListener("click", function () {
          words.splice(index, 1);
          renderTokens();
          sync();
          hooks.changed();
          input.focus();
        });

        token.append(el("span", "", word), remove);
        tokens.appendChild(token);
      });

      tokens.hidden = !words.length;
      hooks.reposition();
    }

    function add(text) {
      split(text).forEach(function (part) {
        if (words.indexOf(part) === -1) {
          words.push(part);
        }
      });

      renderTokens();
    }

    input.addEventListener("keydown", function (event) {
      if (event.key === "," || (event.key === "Tab" && input.value.trim())) {
        event.preventDefault();
        add(input.value);
        input.value = "";
        sync();
      } else if (event.key === "Backspace" && !input.value && words.length) {
        words.pop();
        renderTokens();
        sync();
        hooks.changed();
      }
    });

    input.addEventListener("input", function () {
      sync();
      hooks.changed(true);
    });

    if (column.facets) {
      var load = core.debounce(function () {
        loadValues(controller, column, input.value.trim())
          .then(function (result) {
            suggestions.replaceChildren();

            (result.values || []).slice(0, 8).forEach(function (entry) {
              var item = button("dt-values__suggestion", "");

              item.append(valueNode(entry, column));

              if (entry.count !== undefined) {
                item.appendChild(el("span", "dt-count", formatCount(entry.count)));
              }

              item.addEventListener("click", function () {
                add(entry.label);
                input.value = "";
                sync();
                hooks.changed();
                input.focus();
              });
              suggestions.appendChild(item);
            });

            suggestions.hidden = !suggestions.childNodes.length;
            hooks.reposition();
          })
          .catch(function () {
            suggestions.hidden = true;
          });
      }, 250);

      input.addEventListener("input", load);
      load();
    }

    suggestions.hidden = true;
    node.append(tokens, input, suggestions, el("p", "dt-editor__hint", t("Separate several values with a comma: any of them may match.")));
    renderTokens();
    sync();

    return { node: node };
  }

  function scalarInput(column, value, label) {
    var input = el("input", "input input--sm");

    input.type = query.kind(column) === "date" ? "date" : "number";

    if (input.type === "number") {
      input.step = column.filterType === "integer" ? "1" : "any";
    }

    input.value = value === undefined || value === null ? "" : String(value).slice(0, input.type === "date" ? 10 : undefined);
    input.setAttribute("aria-label", label);

    return input;
  }

  /** The known range of a number or date column, as a hint. */
  function rangeHint(controller, column, hooks) {
    var hint = el("p", "dt-editor__hint");

    hint.hidden = true;

    if (column.facets) {
      loadValues(controller, column, "")
        .then(function (result) {
          if (result.kind !== "range" || result.min === null || result.min === undefined) {
            return;
          }

          var format = function (value) {
            return query.kind(column) === "date" ? core.formatDate(value) : formatCount(value);
          };

          hint.textContent = core.format(t("Values from %(min)s to %(max)s."), {
            min: format(result.min),
            max: format(result.max)
          });

          if (result.empty) {
            hint.textContent +=
              " " + core.format(t("%(count)s empty."), { count: formatCount(result.empty) });
          }

          hint.hidden = false;
          hooks.reposition();
        })
        .catch(function () {});
    }

    return hint;
  }

  function oneEditor(controller, column, draft, hooks) {
    var node = el("div", "dt-values");
    var input = scalarInput(column, draft.value, t("Value"));

    input.dataset.autofocus = "";
    input.addEventListener("input", function () {
      draft.value = readNumber(input);
      hooks.changed(true);
    });

    node.append(input, rangeHint(controller, column, hooks));

    return { node: node };
  }

  function rangeEditor(controller, column, draft, hooks) {
    var node = el("div", "dt-values");
    var row = el("div", "dt-range");
    var value = draft.value && typeof draft.value === "object" && !Array.isArray(draft.value)
      ? draft.value
      : { from: "", to: "" };
    var from = scalarInput(column, value.from, t("From"));
    var to = scalarInput(column, value.to, t("To"));

    draft.value = { from: value.from || "", to: value.to || "" };
    from.dataset.autofocus = "";

    function sync() {
      draft.value = { from: readNumber(from), to: readNumber(to) };
      hooks.changed(true);
    }

    from.addEventListener("input", sync);
    to.addEventListener("input", sync);

    row.append(from, el("span", "dt-range__dash", "\u2013"), to);
    node.append(row, el("p", "dt-editor__hint", t("Leave one side empty for an open range.")), rangeHint(controller, column, hooks));

    return { node: node };
  }

  function daysEditor(controller, column, draft, hooks) {
    var node = el("div", "dt-values dt-days");
    var input = el("input", "input input--sm");

    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.value = draft.value ? String(draft.value) : "30";
    input.dataset.autofocus = "";
    input.setAttribute("aria-label", t("Number of days"));
    draft.value = Number(input.value);

    input.addEventListener("input", function () {
      draft.value = input.value === "" ? "" : Number(input.value);
      hooks.changed(true);
    });

    node.append(input, el("span", "", draft.operator === "older_than_days" ? t("days ago") : t("days")));

    return { node: node };
  }

  /** A searchable list of the values, with their counts. */
  function choicesEditor(controller, column, draft, hooks) {
    var node = el("div", "dt-choices");
    var search = el("input", "input input--sm");
    var list = el("div", "dt-choices__list");
    var status = el("p", "dt-editor__hint");
    var bulk = el("div", "dt-choices__bulk");
    var shownResult = null;
    var selected = (Array.isArray(draft.value) ? draft.value : []).map(String);
    var raw = {};
    var sequence = 0;

    (Array.isArray(draft.value) ? draft.value : []).forEach(function (value) {
      raw[String(value)] = value;
    });

    draft.labels = draft.labels || {};
    search.type = "search";
    search.placeholder = t("Search the values") + "\u2026";
    search.dataset.autofocus = "";
    search.setAttribute("aria-label", t("Search the values"));
    list.setAttribute("role", "group");
    list.setAttribute("aria-label", column.title);

    function sync() {
      draft.value = selected.map(function (key) {
        return Object.prototype.hasOwnProperty.call(raw, key) ? raw[key] : key;
      });
    }

    function row(entry) {
      var key = String(entry.value);
      var item = el("label", "dt-choice");
      var checkbox = el("input");

      raw[key] = entry.value;
      checkbox.type = "checkbox";
      checkbox.checked = selected.indexOf(key) !== -1;
      checkbox.addEventListener("change", function () {
        var index = selected.indexOf(key);

        if (checkbox.checked && index === -1) {
          selected.push(key);
          draft.labels[key] = entry.label;
        } else if (!checkbox.checked && index !== -1) {
          selected.splice(index, 1);
        }

        item.classList.toggle("is-selected", checkbox.checked);
        sync();
        hooks.changed();

        if (shownResult) {
          renderBulk(shownResult.result, shownResult.term);
        }
      });

      item.classList.toggle("is-selected", checkbox.checked);
      item.append(checkbox, valueNode(entry, column));

      if (entry.count !== undefined && entry.count !== null) {
        item.appendChild(el("span", "dt-count", formatCount(entry.count)));
      }

      return item;
    }

    /**
     * What a search found, at once: every value listed ticked (or
     * unticked), or - on a relation - the words themselves, so the
     * filter keeps every record whose name holds them, listed or not.
     */
    function renderBulk(result, term) {
      var values = result.values || [];
      var keys = values.map(function (entry) {
        return String(entry.value);
      });
      var all = keys.length > 0 && keys.every(function (key) {
        return selected.indexOf(key) !== -1;
      });

      bulk.replaceChildren();

      if (term && column.textSearch) {
        var words = button(
          "button button--sm button--ghost dt-choices__words",
          core.format(t("Contains \u201c%(value)s\u201d"), { value: term })
        );

        words.title = t("Keep every row whose value contains these words, listed here or not");
        words.addEventListener("click", function () {
          hooks.setOperator("contains", false, [term]);
        });
        bulk.appendChild(words);
      }

      if (term && keys.length > 1) {
        var toggle = button(
          "button button--sm button--ghost dt-choices__all",
          all
            ? t("Unselect these values")
            : core.format(t("Select the %(count)s values found"), { count: formatCount(keys.length) })
        );

        toggle.addEventListener("click", function () {
          values.forEach(function (entry) {
            var key = String(entry.value);
            var index = selected.indexOf(key);

            raw[key] = entry.value;

            if (all && index !== -1) {
              selected.splice(index, 1);
            } else if (!all && index === -1) {
              selected.push(key);
              draft.labels[key] = entry.label;
            }
          });

          sync();
          hooks.changed();
          render(result, term);
        });
        bulk.appendChild(toggle);
      }

      bulk.hidden = !bulk.childNodes.length;
    }

    function render(result, term) {
      shownResult = { result: result, term: term };
      list.replaceChildren();
      renderBulk(result, term);

      var shown = {};

      (result.values || []).forEach(function (entry) {
        shown[String(entry.value)] = true;
      });

      // What is ticked stays in sight, even outside the results.
      if (!term) {
        selected.forEach(function (key) {
          if (!shown[key]) {
            list.appendChild(row({ value: raw[key], label: draft.labels[key] || key }));
          }
        });
      }

      (result.values || []).forEach(function (entry) {
        list.appendChild(row(entry));
      });

      if (result.empty) {
        var empty = button("dt-choice dt-choice--empty", "");

        empty.append(
          el("span", "dt-value-label", t("Empty")),
          el("span", "dt-count", formatCount(result.empty))
        );
        empty.title = t("Rows without a value");
        empty.addEventListener("click", function () {
          hooks.setOperator("empty", true);
        });
        list.appendChild(empty);
      }

      if (!list.childNodes.length) {
        status.textContent = t("No value found.");
      } else if (result.more) {
        status.textContent = t("More values exist: refine the search.");
      } else {
        status.textContent = "";
      }

      status.hidden = !status.textContent;
      hooks.reposition();
    }

    function load() {
      var current = (sequence += 1);
      var term = search.value.trim();

      status.textContent = t("Loading") + "\u2026";
      status.hidden = false;

      loadValues(controller, column, term)
        .then(function (result) {
          if (current === sequence) {
            render(result, term);
          }
        })
        .catch(function (error) {
          if (current === sequence) {
            status.textContent = (error && error.message) || t("The values could not be loaded.");
            status.hidden = false;
          }
        });
    }

    search.addEventListener("input", core.debounce(load, 250));
    bulk.hidden = true;
    node.append(search, bulk, list, status);
    load();

    return { node: node };
  }

  function valueEditor(controller, column, draft, hooks) {
    var operator = core.findOperator(column, draft.operator);

    switch (operator && operator.arity) {
      case "many":
        return wordsEditor(controller, column, draft, hooks);
      case "one":
        return oneEditor(controller, column, draft, hooks);
      case "range":
        return rangeEditor(controller, column, draft, hooks);
      case "days":
        return daysEditor(controller, column, draft, hooks);
      case "choices":
        return choicesEditor(controller, column, draft, hooks);
      default:
        return null;
    }
  }

  /** The condition as stored: only what its operator uses. */
  function finished(draft, column) {
    var operator = core.findOperator(column, draft.operator);
    var condition = { column: draft.column, operator: draft.operator };

    if (operator.arity !== "none") {
      condition.value = query.clone(draft.value);
    }

    if (operator.arity === "choices" && draft.labels) {
      condition.labels = {};

      (condition.value || []).forEach(function (value) {
        var key = String(value);

        if (Object.prototype.hasOwnProperty.call(draft.labels, key)) {
          condition.labels[key] = draft.labels[key];
        }
      });
    }

    return condition;
  }

  /** How long a run of ticks waits before the table asks for its rows. */
  var LIVE_DELAY = 150;

  /**
   * Open the editor of one condition.
   *
   * `options`: `column`, and `conditionId` to edit an existing one;
   * otherwise a new one lands in `groupId`, in a new group with
   * `newGroup`, or at the top. `after` runs once it is closed with Done.
   *
   * The filter follows the editor as it changes: a value ticked, a
   * condition or a column picked applies at once, a value typed as the
   * typing pauses. There is nothing to apply, only *Done* - which also
   * applies a condition complete from the start, *is yes* - and
   * *Cancel*, which puts the filters back as they were.
   */
  function openEditor(controller, anchor, options) {
    var popover = controller.filterPopover;
    var place = options.conditionId ? query.locate(controller.filterTree, options.conditionId) : null;
    var column = place ? query.columnFor(controller.columns, place.node.column) : options.column;

    if (!column) {
      return;
    }

    var draft = place ? query.clone(place.node) : query.newCondition(column);
    var root = el("form", "dt-editor");
    var head = el("div", "dt-editor__head");
    var columnSelect = el("select", "input input--sm dt-editor__column");
    var operatorSelect = el("select", "input input--sm dt-editor__operator");
    var body = el("div", "dt-editor__body");
    var footer = el("div", "dt-editor__footer");
    var spacer = el("span", "dt-editor__spacer");
    var remove = button("button button--sm button--danger-ghost", t("Remove"), "delete");
    var cancel = button("button button--sm button--ghost", t("Cancel"));
    var apply = el("button", "button button--sm button--primary");
    var editor = null;

    // The condition in the tree this editor stands for, and what it was
    // when the editor opened.
    var currentId = place ? place.node.id : null;
    var original = place ? query.clone(place.node) : null;
    var home = place && place.group !== controller.filterTree ? place.group.id : options.groupId;
    var applied = place ? JSON.stringify(finished(draft, column)) : null;
    var touched = false;
    var typing = null;
    var redrawSoon = core.debounce(function () {
      controller.redraw();
    }, LIVE_DELAY);

    root.noValidate = true;
    columnSelect.setAttribute("aria-label", t("Column"));
    operatorSelect.setAttribute("aria-label", t("Condition"));
    apply.type = "submit";
    apply.textContent = t("Done");

    query.filterable(controller.columns).forEach(function (entry) {
      columnSelect.appendChild(
        new Option(entry.title, query.keyOf(entry), false, entry === column)
      );
    });

    var hooks = {
      reposition: function () {
        popover.position();
      },
      // `typed`: wait for the typing to pause, as the search row does.
      changed: function (typed) {
        window.clearTimeout(typing);

        if (typed) {
          typing = window.setTimeout(applyLive, controller.options.searchDelay || 350);
        } else {
          applyLive();
        }
      },
      setOperator: function (value, submitNow, newValue) {
        draft.operator = value;
        operatorSelect.value = value;

        if (newValue !== undefined) {
          draft.value = newValue;
          delete draft.labels;
        }

        renderValue();
        applyLive();

        if (submitNow) {
          submit();
        }
      }
    };

    function exists() {
      return Boolean(currentId && query.locate(controller.filterTree, currentId));
    }

    /** Put `condition` where this editor's filter is, or lands. */
    function store(condition, redraw) {
      if (exists()) {
        controller.replaceCondition(currentId, condition, redraw);
      } else if (options.newGroup) {
        condition.id = query.uid();
        controller.filterTree.conditions.push({
          id: query.uid(),
          match: query.MATCH_ANY,
          conditions: [condition]
        });
        controller.filtersChanged(redraw);
      } else {
        controller.addCondition(condition, home, redraw);
      }

      currentId = condition.id;
    }

    function drop(redraw) {
      if (exists()) {
        controller.removeCondition(currentId, redraw);
      }

      currentId = null;
    }

    function changedView() {
      if (controller.setActiveView) {
        controller.setActiveView("");
      }
    }

    /** The draft as the table's filter, now: a filter, or none. */
    function applyLive() {
      window.clearTimeout(typing);

      var condition = query.isComplete(draft, column) ? finished(draft, column) : null;
      var text = condition ? JSON.stringify(condition) : null;

      // A pause on the same words, an operator giving the same filter.
      if (text === applied && (condition ? exists() : !exists())) {
        return;
      }

      if (condition) {
        store(condition, false);
      } else {
        drop(false);
      }

      applied = text;
      touched = true;
      changedView();
      redrawSoon();
      updateFooter();
      popover.position();
    }

    /** Cancel: the filters as they were when the editor opened. */
    function revert() {
      window.clearTimeout(typing);

      if (!touched) {
        return;
      }

      if (original) {
        store(query.clone(original));
      } else {
        drop();
      }
    }

    function updateFooter() {
      remove.hidden = !exists();
    }

    function fillOperators() {
      var groups = {};

      operatorSelect.replaceChildren();

      core.operatorsFor(column).forEach(function (entry) {
        var parent = operatorSelect;

        if (entry.group) {
          if (!groups[entry.group]) {
            groups[entry.group] = document.createElement("optgroup");
            groups[entry.group].label = entry.group;
            operatorSelect.appendChild(groups[entry.group]);
          }

          parent = groups[entry.group];
        }

        parent.appendChild(new Option(entry.label, entry.value));
      });

      if (!core.findOperator(column, draft.operator)) {
        draft.operator = core.operatorsFor(column)[0].value;
      }

      operatorSelect.value = draft.operator;
    }

    function renderValue() {
      body.replaceChildren();
      editor = valueEditor(controller, column, draft, hooks);

      if (editor) {
        body.appendChild(editor.node);
      }

      body.hidden = !editor;
      popover.position();

      var focus = body.querySelector("[data-autofocus]");

      if (focus) {
        focus.focus({ preventScroll: true });
      }
    }

    function submit(event) {
      if (event) {
        event.preventDefault();
      }

      // What the typing has not applied yet, and a condition complete
      // from the start that nothing changed.
      applyLive();
      close();
    }

    function close() {
      popover.close(false);

      if (options.after) {
        options.after();
      }
    }

    columnSelect.addEventListener("change", function () {
      column = query.columnFor(controller.columns, columnSelect.value) || column;
      draft = query.newCondition(column);
      fillOperators();
      renderValue();
      applyLive();
    });

    operatorSelect.addEventListener("change", function () {
      var before = core.findOperator(column, draft.operator);
      var after = core.findOperator(column, operatorSelect.value);

      draft.operator = operatorSelect.value;

      // A value only survives a change between operators taking the
      // same kind of value.
      if (!before || !after || before.arity !== after.arity) {
        delete draft.value;
      }

      renderValue();
      applyLive();
    });

    cancel.addEventListener("click", function () {
      revert();
      popover.close(true);
    });

    remove.addEventListener("click", function () {
      window.clearTimeout(typing);
      drop();
      changedView();
      close();
    });

    root.addEventListener("submit", submit);

    footer.append(remove, spacer, cancel, apply);
    head.append(columnSelect, operatorSelect);
    root.append(head, body, footer);

    updateFooter();
    fillOperators();
    popover.open(anchor, root, core.format(t("Filter %(column)s"), { column: column.title }));
    renderValue();
  }

  /* -- Groups ---------------------------------------------------------------- */

  function openGroupEditor(controller, anchor, groupId) {
    var popover = controller.filterPopover;
    var place = query.locate(controller.filterTree, groupId);

    if (!place || !query.isGroup(place.node)) {
      popover.close(false);
      return;
    }

    var group = place.node;
    var root = el("div", "dt-group-editor");
    var head = el("div", "dt-group-editor__head");
    var match = el("select", "input input--sm");
    var list = el("div", "dt-group-editor__list");
    var footer = el("div", "dt-editor__footer");
    var reopen = function () {
      openGroupEditor(controller, anchor, groupId);
    };

    match.setAttribute("aria-label", t("The group matches"));
    match.append(
      new Option(t("Any of these"), query.MATCH_ANY),
      new Option(t("All of these"), query.MATCH_ALL)
    );
    match.value = group.match;
    match.addEventListener("change", function () {
      group.match = match.value;
      controller.filtersChanged();
    });

    head.append(icon("account_tree", "icon--sm"), match);

    group.conditions.forEach(function (condition) {
      if (query.isGroup(condition)) {
        return;
      }

      var column = query.columnFor(controller.columns, condition.column);

      if (!column) {
        return;
      }

      var line = el("div", "dt-group-editor__row");
      var edit = button("dt-group-editor__edit", query.describeText(condition, column));
      var remove = button("icon-button icon-button--sm", "", "close");

      remove.setAttribute("aria-label", t("Remove this condition"));
      edit.addEventListener("click", function () {
        openEditor(controller, anchor, { conditionId: condition.id, after: reopen });
      });
      remove.addEventListener("click", function () {
        controller.removeCondition(condition.id);
        reopen();
      });

      line.append(edit, remove);
      list.appendChild(line);
    });

    var add = button("button button--sm button--ghost", t("Add a condition"), "add");
    var ungroup = button("button button--sm button--danger-ghost", t("Remove the group"), "delete");
    var done = button("button button--sm button--primary", t("Done"));

    add.addEventListener("click", function () {
      openFieldPicker(controller, anchor, { groupId: groupId, after: reopen });
    });
    ungroup.addEventListener("click", function () {
      controller.removeCondition(groupId);
      popover.close(false);
    });
    done.addEventListener("click", function () {
      popover.close(true);
    });

    footer.append(ungroup, el("span", "dt-editor__spacer"), done);
    root.append(head, list, add, footer);
    popover.open(anchor, root, t("Group of conditions"));
  }

  /* -- The bar ----------------------------------------------------------------- */

  function conditionChip(controller, condition) {
    var column = query.columnFor(controller.columns, condition.column);

    if (!column) {
      return null;
    }

    var parts = query.describe(condition, column);
    var chip = el("span", "dt-chip" + (query.isComplete(condition, column) ? "" : " is-incomplete"));
    var body = el("button", "dt-chip__body");
    var remove = button("dt-chip__remove", "", "close");

    body.type = "button";
    body.title = query.describeText(condition, column);
    body.append(el("span", "dt-chip__field", parts.field), el("span", "dt-chip__operator", parts.operator));

    if (parts.value) {
      body.appendChild(el("span", "dt-chip__value", parts.value));
    }

    body.addEventListener("click", function () {
      if (controller.filterPopover.isOpenFor(chip)) {
        controller.filterPopover.close(true);
        return;
      }

      openEditor(controller, chip, { conditionId: condition.id });
    });

    remove.setAttribute("aria-label", core.format(t("Remove the filter %(filter)s"), { filter: body.title }));
    remove.addEventListener("click", function () {
      controller.removeCondition(condition.id);
    });

    chip.append(body, remove);

    return chip;
  }

  function groupChip(controller, group) {
    var chip = el("span", "dt-chip dt-chip--group");
    var body = el("button", "dt-chip__body");
    var remove = button("dt-chip__remove", "", "close");
    var summary = group.conditions
      .map(function (condition) {
        var column = !query.isGroup(condition) && query.columnFor(controller.columns, condition.column);

        return column ? query.describeText(condition, column) : "";
      })
      .filter(Boolean);

    body.type = "button";
    body.title = summary.join(group.match === query.MATCH_ANY ? " " + t("or") + " " : " " + t("and") + " ");
    body.append(
      icon("account_tree", "icon--sm"),
      el("span", "dt-chip__field", group.match === query.MATCH_ANY ? t("Any of") : t("All of")),
      el("span", "dt-chip__value", summary.join(" \u00b7 "))
    );
    body.addEventListener("click", function () {
      openGroupEditor(controller, chip, group.id);
    });

    remove.setAttribute("aria-label", t("Remove the group"));
    remove.addEventListener("click", function () {
      controller.removeCondition(group.id);
    });

    chip.append(body, remove);

    return chip;
  }

  function renderBar(controller) {
    var bar = controller.filterBar;
    var tree = controller.filterTree;

    if (!bar) {
      return;
    }

    bar.replaceChildren();
    bar.hidden = !tree.conditions.length;

    if (bar.hidden) {
      return;
    }

    bar.appendChild(icon("filter_list", "icon--sm dt-filterbar__icon"));

    if (tree.conditions.length > 1) {
      var match = el("select", "input input--sm dt-filterbar__match");

      match.setAttribute("aria-label", t("Rows must match"));
      match.append(
        new Option(t("All of"), query.MATCH_ALL),
        new Option(t("Any of"), query.MATCH_ANY)
      );
      match.value = tree.match;
      match.addEventListener("change", function () {
        tree.match = match.value;
        controller.filtersChanged();
      });
      bar.appendChild(match);
    }

    tree.conditions.forEach(function (node) {
      var chip = query.isGroup(node) ? groupChip(controller, node) : conditionChip(controller, node);

      if (chip) {
        bar.appendChild(chip);
      }
    });

    var add = button("dt-filterbar__add", t("Add"), "add");
    var clear = button("dt-filterbar__clear", t("Clear all"));

    add.title = t("Add a filter");
    add.addEventListener("click", function () {
      openFieldPicker(controller, add);
    });
    clear.addEventListener("click", function () {
      controller.clearFilters();
      controller.redraw();

      if (controller.setActiveView) {
        controller.setActiveView("");
      }
    });

    bar.append(add, clear);
  }

  /* -- Column headers -------------------------------------------------------------- */

  function openColumnFilter(controller, column, anchor) {
    var popover = controller.filterPopover;

    if (popover.isOpenFor(anchor)) {
      popover.close(true);
      return;
    }

    var existing = controller.filterTree.conditions.filter(function (node) {
      return !query.isGroup(node) && node.column === query.keyOf(column);
    });

    openEditor(
      controller,
      anchor,
      existing.length ? { conditionId: existing[existing.length - 1].id } : { column: column }
    );
  }

  function decorateHeader(controller) {
    var api = controller.instance;

    controller.dataColumns().forEach(function (entry) {
      var column = entry.column;

      if (column.searchable === false) {
        return;
      }

      var cell = api.column(entry.index).header();

      if (!cell) {
        return;
      }

      var trigger = cell.querySelector(".dt-head-filter");

      if (!trigger) {
        var label = core.format(t("Filter %(column)s"), { column: column.title });

        trigger = button("dt-head-filter", "", "filter_alt");
        trigger.title = label;
        trigger.setAttribute("aria-label", label);

        // The header orders the table on a click or a key: this button
        // must not.
        ["mousedown", "keydown", "keyup", "keypress"].forEach(function (type) {
          trigger.addEventListener(type, function (event) {
            event.stopPropagation();
          });
        });

        trigger.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          openColumnFilter(controller, column, cell);
        });

        (cell.querySelector(".dt-column-header") || cell).appendChild(trigger);
      }

      var active = query.conditionsOn(controller.filterTree, query.keyOf(column)).some(function (condition) {
        return query.isComplete(condition, column);
      });

      cell.classList.toggle("is-filtered", active);
      trigger.classList.toggle("is-active", active);
    });
  }

  /* -- The toolbar button ---------------------------------------------------------- */

  function buildTools(controller) {
    var group = el("div", "dt-filter-tools");
    var trigger = el("button", "button button--sm dt-tool");
    var count = el("span", "badge-count");
    var clear = button("icon-button icon-button--sm", "", "filter_list_off");

    controller.filterTrigger = trigger;
    trigger.type = "button";
    trigger.title = t("Add a filter") + " (F)";
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-keyshortcuts", "F");
    trigger.append(icon("filter_list", "icon--sm"), el("span", "dt-tool__label", t("Filter")), count);
    count.hidden = true;

    clear.title = t("Clear every filter");
    clear.setAttribute("aria-label", t("Clear every filter"));
    clear.hidden = true;

    trigger.addEventListener("click", function (event) {
      event.stopPropagation();

      if (controller.filterPopover && controller.filterPopover.isOpenFor(trigger)) {
        controller.filterPopover.close(true);
        return;
      }

      openFieldPicker(controller, trigger);
    });

    clear.addEventListener("click", function () {
      controller.clearFilters();
      controller.redraw();

      if (controller.setActiveView) {
        controller.setActiveView("");
      }
    });

    controller.updateFilterCount = function () {
      var active = controller.activeFilterCount();

      count.hidden = active === 0;
      count.textContent = String(active);
      clear.hidden = active === 0;
      trigger.classList.toggle("is-active", active > 0);
    };

    group.append(trigger, clear);

    return group;
  }

  /* -- The search box ------------------------------------------------------------------
   *
   * Free words search every column, as before. A word shaped
   * `name:value` becomes a filter as soon as it is followed by a space
   * or Enter; while it is typed, a list suggests the columns, then the
   * values.
   */

  /** Merge "status:open" into an existing "status is any of" filter. */
  function addTyped(controller, condition) {
    if (condition.operator === "any_of" || condition.operator === "none_of") {
      var same = controller.filterTree.conditions.find(function (node) {
        return !query.isGroup(node) && node.column === condition.column && node.operator === condition.operator;
      });

      if (same) {
        var values = (same.value || []).map(String);

        (condition.value || []).forEach(function (value) {
          if (values.indexOf(String(value)) === -1) {
            same.value.push(value);
          }
        });

        same.labels = Object.assign({}, same.labels || {}, condition.labels || {});
        controller.filtersChanged();

        return;
      }
    }

    delete condition.unresolved;
    controller.addCondition(condition);
  }

  /** Look up the values typed by label: "team:front" -> the team's key. */
  function resolveTyped(controller, column, condition) {
    var Generic = generic();
    var pending = condition.unresolved || [];

    return Promise.all(
      pending.map(function (label) {
        return loadValues(controller, column, label).then(function (result) {
          var wanted = String(label).toLowerCase();
          var values = result.values || [];
          var exact = values.find(function (entry) {
            return String(entry.label).toLowerCase() === wanted;
          });

          return exact || (values.length === 1 ? values[0] : null) || { missing: label };
        });
      })
    ).then(function (entries) {
      var words = [];

      entries.forEach(function (entry) {
        if (entry.missing && column.textSearch) {
          // Not one value's name: the words the names contain.
          words.push(entry.missing);
          return;
        }

        if (entry.missing) {
          if (Generic) {
            Generic.toast(
              core.format(t("%(column)s has no value \u201c%(value)s\u201d."), {
                column: column.title,
                value: entry.missing
              }),
              "warning"
            );
          }

          return;
        }

        condition.value.push(entry.value);
        condition.labels[String(entry.value)] = entry.label;
      });

      delete condition.unresolved;

      if (condition.value.length) {
        addTyped(controller, condition);
      }

      if (words.length) {
        addTyped(controller, {
          id: query.uid(),
          column: condition.column,
          operator: condition.operator === "none_of" ? "not_contains" : "contains",
          value: words
        });
      }
    });
  }

  function bindSmartSearch(controller) {
    var input = controller.searchInput;

    if (!input) {
      return;
    }

    var box = el("div", "dt-suggest");
    var items = [];
    var active = -1;
    var sequence = 0;

    box.hidden = true;
    box.id = "dt-suggest-" + query.uid();
    box.setAttribute("role", "listbox");
    document.body.appendChild(box);
    controller.suggestBox = box;

    input.placeholder = t("Search or filter") + "\u2026";
    input.title = t(
      "Words search every column; put ! before one to exclude it. " +
        "name:value filters a column: status:open, hours:>2, " +
        "opened:30d, due:2026-01-01..2026-03-31, -tags:billing, " +
        "assignee:empty."
    );
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", box.id);

    controller.freeSearchText = function (value) {
      return query.parse(value, controller.columns).free.trim();
    };

    function hide() {
      box.hidden = true;
      items = [];
      active = -1;
      input.setAttribute("aria-expanded", "false");
    }

    function position() {
      var rect = input.getBoundingClientRect();

      box.style.left = Math.max(8, rect.left) + "px";
      box.style.top = rect.bottom + 4 + "px";
      box.style.minWidth = rect.width + "px";
    }

    function highlight() {
      Array.from(box.children).forEach(function (child, index) {
        child.classList.toggle("is-active", index === active);
        child.setAttribute("aria-selected", String(index === active));
      });
    }

    function show(entries) {
      box.replaceChildren();
      items = entries;
      active = entries.findIndex(function (entry) {
        return Boolean(entry.apply);
      });

      entries.forEach(function (entry, index) {
        var item = el("div", "dt-suggest__item" + (entry.apply ? "" : " is-info"));

        item.setAttribute("role", "option");

        if (entry.icon) {
          item.appendChild(icon(entry.icon, "icon--sm"));
        }

        item.appendChild(entry.tag ? valueNode(entry, null) : el("span", "dt-suggest__label", entry.label));

        if (entry.hint) {
          item.appendChild(el("span", "dt-suggest__hint", entry.hint));
        }

        if (entry.count !== undefined && entry.count !== null) {
          item.appendChild(el("span", "dt-count", formatCount(entry.count)));
        }

        item.addEventListener("mousedown", function (event) {
          // Keep the focus in the box.
          event.preventDefault();
          pick(index);
        });

        box.appendChild(item);
      });

      box.hidden = !entries.length;
      input.setAttribute("aria-expanded", String(!box.hidden));
      highlight();
      position();
    }

    function tokenAtCaret() {
      var value = input.value;
      var caret = input.selectionStart === null ? value.length : input.selectionStart;
      var start = value.lastIndexOf(" ", caret - 1) + 1;
      var end = value.indexOf(" ", caret);

      end = end === -1 ? value.length : end;

      return { text: value.slice(start, end), start: start, end: end };
    }

    function replaceToken(token, replacement) {
      var value = input.value;

      input.value = value.slice(0, token.start) + replacement + value.slice(token.end);

      var caret = token.start + replacement.length;

      input.setSelectionRange(caret, caret);
      input.dispatchEvent(new CustomEvent("generic:sync"));
    }

    function removeToken(token) {
      var value = input.value;
      var before = value.slice(0, token.start).replace(/\s+$/, "");
      var after = value.slice(token.end).replace(/^\s+/, "");

      input.value = before && after ? before + " " + after : before + after;
      input.setSelectionRange(before.length, before.length);
      input.dispatchEvent(new CustomEvent("generic:sync"));
    }

    function search() {
      controller.instance.search(controller.freeSearchText(input.value));
      controller.redraw();
    }

    function pick(index) {
      var entry = items[index];

      if (entry && entry.apply) {
        entry.apply();
      }
    }

    function valueEntries(column, token, typed, negated) {
      var key = query.keyOf(column);
      var group = query.kind(column);
      var current = (sequence += 1);
      var prefix = (negated ? "-" : "") + key + ":";
      var word = function (text, label, hint) {
        return {
          label: label,
          hint: hint || prefix + text,
          apply: function () {
            replaceToken(token, prefix + text + " ");
            commit(false);
            search();
            update();
          }
        };
      };
      var starts = function (entry) {
        return !typed || entry.hint.toLowerCase().indexOf((prefix + typed).toLowerCase()) === 0;
      };

      if (group === "boolean") {
        show([word("yes", t("Yes")), word("no", t("No")), word("empty", t("Empty"))].filter(starts));
        return;
      }

      if (group === "date") {
        show(
          [
            word("today", t("Today")),
            word("this-week", t("This week")),
            word("this-month", t("This month")),
            word("last-month", t("Last month")),
            word("7d", t("The last 7 days")),
            word("30d", t("The last 30 days")),
            word("this-year", t("This year")),
            word("empty", t("Empty"))
          ]
            .filter(starts)
            .concat(typed ? [] : [{ label: t("Or a date: >=2026-01-01, 2026-01-01..2026-03-31") }])
        );
        return;
      }

      if (group === "number") {
        show(typed ? [] : [{ label: t("A number: 5, >10, <=2.5, 2..8, empty") }]);
        return;
      }

      if (group !== "multiselect" && !column.facets) {
        show(typed ? [] : [{ label: t("A word, several with commas, =exact, empty") }]);
        return;
      }

      loadValues(controller, column, typed)
        .then(function (result) {
          if (current !== sequence) {
            return;
          }

          show(
            (result.values || []).slice(0, 8).map(function (entry) {
              return {
                label: entry.label,
                tag: entry.tag,
                count: entry.count,
                apply: function () {
                  var condition = group === "multiselect"
                    ? {
                        column: key,
                        operator: negated ? "none_of" : "any_of",
                        value: [entry.value],
                        labels: {}
                      }
                    : { column: key, operator: negated ? "not_equals" : "equals", value: [entry.label] };

                  if (condition.labels) {
                    condition.labels[String(entry.value)] = entry.label;
                  }

                  removeToken(token);
                  addTyped(controller, condition);
                  search();
                  hide();
                }
              };
            })
          );
        })
        .catch(hide);
    }

    function update() {
      var token = tokenAtCaret();
      var match = /^([-!]?)([^\s:"]*)(:?)(.*)$/.exec(token.text);

      if (!token.text || !match) {
        hide();
        return;
      }

      if (!match[3]) {
        if (match[2].length < 2) {
          hide();
          return;
        }

        var columns = query.suggestColumns(controller.columns, match[2]).slice(0, 6);

        show(
          columns.map(function (column) {
            return {
              icon: KIND_ICONS[query.kind(column)],
              label: column.title,
              hint: query.keyOf(column) + ":",
              apply: function () {
                replaceToken(token, match[1] + query.keyOf(column) + ":");
                update();
              }
            };
          })
        );
        return;
      }

      var column = query.findColumn(controller.columns, match[2]);

      if (!column) {
        hide();
        return;
      }

      valueEntries(column, token, match[4].replace(/^"/, "").replace(/"$/, ""), Boolean(match[1]));
    }

    /**
     * Turn the finished `name:value` words into filters. While typing
     * (`final` false) only words already followed by a space are.
     */
    function commit(final) {
      var parsed = query.parse(input.value, controller.columns);
      var done = [];

      parsed.tokens.forEach(function (token) {
        var followed = input.value.charAt(token.end) === " ";

        if (!token.condition || token.partial || (!final && !followed)) {
          return;
        }

        done.push(token);

        if (token.condition.unresolved) {
          resolveTyped(controller, token.column, token.condition).catch(function () {});
        } else {
          addTyped(controller, token.condition);
        }
      });

      done.reverse().forEach(removeToken);

      return done.length > 0;
    }

    input.addEventListener("input", function () {
      if (/\s$/.test(input.value)) {
        commit(false);
      }

      update();
    });

    input.addEventListener("click", update);
    input.addEventListener("keyup", function (event) {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "Home" || event.key === "End") {
        update();
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(hide, 150);
    });

    // Asked by the toolbar before it handles a key itself.
    controller.onSearchKeydown = function (event) {
      if (!box.hidden && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();

        var step = event.key === "ArrowDown" ? 1 : -1;
        var next = active;

        // Only entries that do something take the highlight.
        for (var tries = 0; tries < items.length; tries += 1) {
          next = (next + step + items.length) % items.length;

          if (items[next] && items[next].apply) {
            active = next;
            break;
          }
        }

        highlight();

        return true;
      }

      if (event.key === "Escape" && !box.hidden) {
        event.preventDefault();
        hide();
        return true;
      }

      if ((event.key === "Enter" || event.key === "Tab") && !box.hidden && active >= 0 && items[active] && items[active].apply) {
        event.preventDefault();
        pick(active);
        return true;
      }

      if (event.key === "Enter") {
        commit(true);
        hide();
      }

      return false;
    };

    controller.listen(window, "resize", hide);
    controller.listen(
      window,
      "scroll",
      function (event) {
        if (!box.contains(event.target)) {
          hide();
        }
      },
      true
    );
  }

  /* -- A right click on a cell ------------------------------------------------------ */

  /** The value of a choice or relation cell, with its label. */
  function cellChoice(column, row, target) {
    var value = row[column.data];
    var key = row["_fk_" + column.data];

    if (key !== undefined && key !== null) {
      return { value: key, label: String(value) };
    }

    var choices = column.choices || [];

    if (Array.isArray(value)) {
      var tagNode = target && target.closest ? target.closest(".tag") : null;
      var tag = tagNode
        ? value.find(function (item) {
            return item && String(item.label) === tagNode.textContent.trim();
          })
        : value.length === 1
          ? value[0]
          : null;

      if (!tag) {
        return null;
      }

      if (tag.id !== undefined && tag.id !== null) {
        return { value: tag.id, label: tag.label };
      }

      var byLabel = choices.find(function (choice) {
        return String(choice.label) === String(tag.label);
      });

      return byLabel ? { value: byLabel.value, label: byLabel.label } : null;
    }

    var choice = choices.find(function (entry) {
      return String(entry.value) === String(value);
    });

    return choice ? { value: choice.value, label: choice.label } : null;
  }

  /**
   * "Only this value" and "anything but" for the cell under a right
   * click, as row menu entries: `[{label, icon, run}]`.
   */
  function quickFilters(controller, column, row, target) {
    if (!column || column.synthetic || column.searchable === false || !row) {
      return [];
    }

    var key = query.keyOf(column);
    var raw = row[column.data];
    var group = query.kind(column);
    var entries = [];

    function add(iconName, condition) {
      condition.id = query.uid();
      entries.push({
        icon: iconName,
        label: query.describeText(condition, column),
        run: function () {
          addTyped(controller, condition);
        }
      });
    }

    if (raw === null || raw === undefined || raw === "" || (Array.isArray(raw) && !raw.length)) {
      add("filter_alt", { column: key, operator: "empty" });
      add("filter_alt_off", { column: key, operator: "not_empty" });
      return entries;
    }

    if (group === "multiselect") {
      var picked = cellChoice(column, row, target);

      if (picked) {
        var labels = {};

        labels[String(picked.value)] = picked.label;
        add("filter_alt", { column: key, operator: "any_of", value: [picked.value], labels: labels });
        add("filter_alt_off", { column: key, operator: "none_of", value: [picked.value], labels: query.clone(labels) });
      }
    } else if (group === "boolean") {
      var truthy = raw === true || raw === "true" || raw === 1;

      add("filter_alt", { column: key, operator: truthy ? "is_true" : "is_false" });
    } else if (group === "date") {
      var day = String(raw).slice(0, 10);

      if (/^\d{4}-\d{2}-\d{2}$/.test(day)) {
        add("filter_alt", { column: key, operator: "on", value: day });
        add("filter_alt_off", { column: key, operator: "not_on", value: day });
        add("start", { column: key, operator: "on_or_after", value: day });
        add("last_page", { column: key, operator: "on_or_before", value: day });
      }
    } else if (group === "number") {
      add("filter_alt", { column: key, operator: "equals", value: String(raw) });
      add("filter_alt_off", { column: key, operator: "not_equals", value: String(raw) });
      add("keyboard_double_arrow_up", { column: key, operator: "gte", value: String(raw) });
      add("keyboard_double_arrow_down", { column: key, operator: "lte", value: String(raw) });
    } else {
      var text = Array.isArray(raw) ? columnsModule.tagLabels(raw) : String(raw);

      if (text.length <= 200) {
        add("filter_alt", { column: key, operator: "equals", value: [text] });
        add("filter_alt_off", { column: key, operator: "not_equals", value: [text] });
      }
    }

    return entries;
  }

  /* -- Labels of restored filters ------------------------------------------------------ */

  /**
   * A filter coming from a link or an older saved view may hold keys
   * without their labels: ask for them once, then redraw the chips.
   */
  function resolveLabels(controller) {
    query.flatten(controller.filterTree).forEach(function (condition) {
      var column = query.columnFor(controller.columns, condition.column);

      if (!column || query.kind(column) !== "multiselect" || !Array.isArray(condition.value)) {
        return;
      }

      condition.labels = condition.labels || {};

      var missing = condition.value.filter(function (value) {
        var key = String(value);
        var fixed = (column.choices || []).some(function (choice) {
          return String(choice.value) === key;
        });

        return !fixed && !Object.prototype.hasOwnProperty.call(condition.labels, key);
      });

      if (!missing.length) {
        return;
      }

      var source = column.autocompleteUrl ? Object.assign({}, column, { facets: false }) : column;

      loadValues(controller, source, "", missing)
        .then(function (result) {
          (result.values || []).forEach(function (entry) {
            condition.labels[String(entry.value)] = entry.label;
          });
          renderBar(controller);

          if (controller.renderFilterRow) {
            controller.renderFilterRow();
          }
        })
        .catch(function () {});
    });
  }

  /* -- The feature ---------------------------------------------------------------------- */

  core.registerFeature({
    name: "filterbar",

    enabled: function (controller) {
      return controller.options.filters !== false;
    },

    top: function (controller) {
      var bar = el("div", "dt-filterbar");

      bar.hidden = true;
      bar.setAttribute("role", "group");
      bar.setAttribute("aria-label", t("Active filters"));
      controller.filterBar = bar;

      return bar;
    },

    init: function (controller) {
      var api = controller.instance;

      controller.filterPopover = new Popover(controller);

      function refresh() {
        renderBar(controller);
        decorateHeader(controller);

        if (controller.updateFilterCount) {
          controller.updateFilterCount();
        }
      }

      controller.table.addEventListener("generic:filters-change", refresh);

      api.on("draw", function () {
        decorateHeader(controller);
        controller.writeLink();

        // A filter applied as it is ticked redraws under its open
        // editor, which follows its anchor if the rows moved it.
        if (controller.filterPopover) {
          controller.filterPopover.position();
        }

        if (controller.updateFilterCount) {
          controller.updateFilterCount();
        }
      });

      api.on("column-visibility", function () {
        decorateHeader(controller);
      });

      // F opens the filters of the page's own table - the one owning
      // the address - unless the user is typing somewhere.
      if (controller.options.syncUrl) {
        controller.listen(document, "keydown", function (event) {
          var target = event.target;

          if (
            (event.key !== "f" && event.key !== "F") ||
            event.ctrlKey ||
            event.metaKey ||
            event.altKey ||
            (target && (target.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName))) ||
            document.querySelector(".dialog[open], dialog[open]") ||
            !controller.filterTrigger ||
            !controller.filterTrigger.offsetParent
          ) {
            return;
          }

          event.preventDefault();
          openFieldPicker(controller, controller.filterTrigger);
        });
      }

      bindSmartSearch(controller);
      refresh();
      resolveLabels(controller);
    },

    destroy: function (controller) {
      if (controller.filterPopover) {
        controller.filterPopover.destroy();
        controller.filterPopover = null;
      }

      if (controller.suggestBox) {
        controller.suggestBox.remove();
        controller.suggestBox = null;
      }
    }
  });

  namespace.filterbar = {
    buildTools: buildTools,
    loadValues: loadValues,
    openEditor: openEditor,
    openFieldPicker: openFieldPicker,
    quickFilters: quickFilters
  };
})(window, document);

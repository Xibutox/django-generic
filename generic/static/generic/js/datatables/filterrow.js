/**
 * A row of search fields under the column headers.
 *
 * The quickest way to filter one column: type under its title. The row
 * is one short line, and only there when asked for - a button beside
 * Filter shows and hides it, and the table remembers the choice. A
 * resource may show it from the start (`filter_row = "open"`).
 *
 *   text      words it contains; =exact, ^start, a,b for any of
 *   number    5, >10, <=2.5, 2..8
 *   date      2026-01-01, >=2026-01-01, 30d, this-month, a..b; the
 *             calendar opens the full editor
 *   boolean   a list: yes, no, empty
 *   choices   a button opening the values with their counts
 *
 * `empty` works in every field, and `!` before the text excludes it.
 *
 * A field edits the condition on its column at the top of the filter
 * tree - the one its chip shows - so the row, the chips and the header
 * funnels are three views of the same filters (table.js). A column
 * filtered in a way one field cannot say - two conditions, "more than N
 * days ago" - shows its filter in words instead, opening its editor.
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var query = namespace.query;
  var el = core.el;
  var icon = core.icon;
  var t = core.t;

  var OPEN = "open";

  /** "open", "toggle", or "" when this table has no row. */
  function modeOf(controller) {
    var value = controller.options.filterRow;

    if (!value || controller.options.filters === false || !namespace.filterbar) {
      return "";
    }

    return value === OPEN ? OPEN : "toggle";
  }

  /* -- Conditions and text -------------------------------------------------- */

  /** The conditions a field edits: those on its column, outside groups. */
  function ownConditions(controller, column) {
    var key = query.keyOf(column);

    return controller.filterTree.conditions.filter(function (node) {
      return !query.isGroup(node) && node.column === key;
    });
  }

  /** What a field's text means, or null when it means nothing yet. */
  function readText(column, text) {
    var value = String(text || "").trim();
    var negated = value.charAt(0) === "!";

    if (negated) {
      value = value.slice(1).trim();
    }

    return value ? query.conditionFromText(column, value, negated) : null;
  }

  function plain(value) {
    if (Array.isArray(value)) {
      return value.map(plain);
    }

    if (value && typeof value === "object") {
      return { from: plain(value.from), to: plain(value.to) };
    }

    return value === undefined || value === null ? "" : String(value);
  }

  /** Whether two conditions filter the same way, whatever their ids. */
  function same(first, second) {
    return (
      first.operator === second.operator &&
      JSON.stringify(plain(first.value)) === JSON.stringify(plain(second.value))
    );
  }

  /**
   * A condition as a field shows it - `>=2`, `!billing`, `30d` - or null
   * when a field could not read it back the same.
   */
  function textOf(condition, column) {
    var match = /^(-?)[^:]*:(.*)$/.exec(query.toText(condition, column));

    if (!match || !match[2]) {
      return null;
    }

    var text = (match[1] ? "!" : "") + match[2];
    var back = readText(column, text);

    return back && same(back, condition) ? text : null;
  }

  /** A column's filters in a few words, for a field that cannot type them. */
  function summaryOf(conditions, column) {
    if (conditions.length > 1) {
      return core.format(t("%(count)s filters"), { count: conditions.length });
    }

    var parts = query.describe(conditions[0], column);

    // "Open, Pending" says "is any of" by itself.
    if (conditions[0].operator === "any_of" && parts.value) {
      return parts.value;
    }

    return [parts.operator, parts.value].filter(Boolean).join(" ");
  }

  function describeAll(conditions, column) {
    return conditions
      .map(function (condition) {
        return query.describeText(condition, column);
      })
      .join(" \u00b7 ");
  }

  /* -- Changing the filters --------------------------------------------------- */

  /**
   * Put `condition` in place of the field's own, or take it away when
   * null. The field being typed in is left alone while the table
   * redraws the row, so its text is not rewritten under the caret.
   */
  function commit(controller, column, condition) {
    var row = controller.filterRow;
    var own = ownConditions(controller, column);
    var current = own[0] || null;

    // Two conditions: the field shows words and does not edit them.
    if (own.length > 1) {
      return;
    }

    if (condition ? current && same(condition, current) : !current) {
      return;
    }

    row.editing = query.keyOf(column);

    try {
      if (!condition) {
        controller.removeCondition(current.id);
      } else if (current) {
        controller.replaceCondition(current.id, condition);
      } else {
        controller.addCondition(condition);
      }
    } finally {
      row.editing = null;
    }

    if (controller.setActiveView) {
      controller.setActiveView("");
    }
  }

  /** The full editor of the column, under `anchor`; a second click closes it. */
  function openEditor(controller, column, anchor) {
    var popover = controller.filterPopover;

    if (!popover) {
      return;
    }

    if (popover.isOpenFor(anchor)) {
      popover.close(true);
      return;
    }

    var own = ownConditions(controller, column);

    namespace.filterbar.openEditor(
      controller,
      anchor,
      own.length ? { conditionId: own[own.length - 1].id } : { column: column }
    );
  }

  /* -- Fields --------------------------------------------------------------------
   *
   * Each returns { control, render }: `control` takes the focus when the
   * row opens, `render` shows the filters as they are now.
   */

  function fieldLabel(column) {
    return core.format(t("Filter %(column)s"), { column: column.title });
  }

  /** A button standing for the column's filters, opening their editor. */
  function pickerButton(controller, column, extraClass) {
    var node = el("button", "dt-filter-field__input dt-filter-field__picker" + (extraClass ? " " + extraClass : ""));
    var label = el("span", "dt-filter-field__label");

    node.type = "button";
    node.setAttribute("aria-haspopup", "dialog");
    node.append(label, icon("arrow_drop_down", "icon--sm"));
    node.addEventListener("click", function () {
      openEditor(controller, column, node);
    });

    node.show = function (conditions) {
      var empty = !conditions.length;

      label.textContent = empty ? t("All") : summaryOf(conditions, column);
      node.classList.toggle("is-empty", empty);
      node.title = empty ? fieldLabel(column) : describeAll(conditions, column);
      node.setAttribute("aria-label", empty ? fieldLabel(column) : fieldLabel(column) + ": " + node.title);
    };

    return node;
  }

  var PLACEHOLDERS = {
    text: function () {
      return t("Contains") + "\u2026";
    },
    number: function () {
      return t("e.g. >10");
    },
    date: function () {
      return t("e.g. 30d");
    }
  };

  var HINTS = {
    text: function () {
      return t("Words the column contains. =word for the exact value, ^word for its start, commas for any of several, !word to exclude, empty for no value.");
    },
    number: function () {
      return t("A number: 5, >10, <=2.5, 2..8, !5 to exclude, empty for no value.");
    },
    date: function () {
      return t("A date: 2026-01-01, >=2026-01-01, 2026-01-01..2026-03-31, 30d for the last 30 days, this-month, empty for no value.");
    }
  };

  /** Words, numbers and dates: typed, applied as the user pauses. */
  function textField(controller, column, cell) {
    var group = query.kind(column);
    var key = query.keyOf(column);
    var wrap = el("div", "dt-filter-field dt-filter-field--" + group);
    var input = el("input", "dt-filter-field__input");
    var words = pickerButton(controller, column, "dt-filter-field__summary");
    var hint = HINTS[group]();

    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.placeholder = PLACEHOLDERS[group]();
    input.title = hint;
    input.setAttribute("aria-label", fieldLabel(column));
    words.hidden = true;

    function invalid(flag) {
      input.classList.toggle("is-invalid", flag);
      input.title = flag
        ? core.format(t("Not understood: %(text)s"), { text: input.value.trim() }) + "\n" + hint
        : hint;

      if (flag) {
        input.setAttribute("aria-invalid", "true");
      } else {
        input.removeAttribute("aria-invalid");
      }
    }

    // While typing, text that means nothing yet - ">", "2026-0" - is
    // simply not applied; Enter or leaving the field says so.
    function apply(final) {
      var text = input.value.trim();
      var condition = text ? readText(column, text) : null;

      if (text && !condition) {
        if (final) {
          invalid(true);
        }

        return;
      }

      invalid(false);
      commit(controller, column, condition);
    }

    var pause = core.debounce(function () {
      apply(false);
    }, controller.options.searchDelay || 350);

    input.addEventListener("input", function () {
      invalid(false);
      pause();
    });

    input.addEventListener("change", function () {
      apply(true);
    });

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        apply(true);
      } else if (event.key === "Escape" && input.value) {
        event.preventDefault();
        event.stopPropagation();
        input.value = "";
        apply(true);
      }
    });

    wrap.append(input, words);

    if (group === "date") {
      var calendar = el("button", "dt-filter-field__button");

      calendar.type = "button";
      calendar.title = t("Pick dates or a period");
      calendar.setAttribute(
        "aria-label",
        core.format(t("Pick dates or a period for %(column)s"), { column: column.title })
      );
      calendar.setAttribute("aria-haspopup", "dialog");
      calendar.appendChild(icon("calendar_month", "icon--sm"));
      calendar.addEventListener("click", function () {
        openEditor(controller, column, calendar);
      });
      wrap.appendChild(calendar);
    }

    cell.appendChild(wrap);

    return {
      control: input,
      render: function (row) {
        var own = ownConditions(controller, column);
        var text = own.length === 0 ? "" : own.length === 1 ? textOf(own[0], column) : null;
        var showWords = text === null;

        wrap.classList.toggle("is-summary", showWords);
        input.hidden = showWords;
        words.hidden = !showWords;

        if (showWords) {
          words.show(own);
        } else if (row.editing !== key) {
          input.value = text;
          invalid(false);
        }

        cell.classList.toggle("is-filtered", own.length > 0);
      },
      focusable: function () {
        return input.hidden ? words : input;
      }
    };
  }

  var BOOLEAN_OPERATORS = { yes: "is_true", no: "is_false", empty: "empty" };

  function booleanField(controller, column, cell) {
    var key = query.keyOf(column);
    var wrap = el("div", "dt-filter-field dt-filter-field--boolean");
    var select = el("select", "dt-filter-field__input dt-filter-field__select");
    var words = pickerButton(controller, column, "dt-filter-field__summary");

    select.setAttribute("aria-label", fieldLabel(column));
    select.append(
      new Option(t("All"), ""),
      new Option(t("Yes"), "yes"),
      new Option(t("No"), "no"),
      new Option(t("Empty"), "empty")
    );
    words.hidden = true;

    select.addEventListener("change", function () {
      var operator = BOOLEAN_OPERATORS[select.value];

      select.classList.toggle("is-empty", !select.value);
      commit(controller, column, operator ? { id: query.uid(), column: key, operator: operator } : null);
    });

    wrap.append(select, words);
    cell.appendChild(wrap);

    return {
      control: select,
      render: function () {
        var own = ownConditions(controller, column);
        var value = "";

        if (own.length === 1) {
          value = Object.keys(BOOLEAN_OPERATORS).find(function (word) {
            return BOOLEAN_OPERATORS[word] === own[0].operator;
          });
        }

        var showWords = value === undefined || own.length > 1;

        select.hidden = showWords;
        words.hidden = !showWords;

        if (showWords) {
          words.show(own);
        } else {
          select.value = value;
          select.classList.toggle("is-empty", !value);
        }

        cell.classList.toggle("is-filtered", own.length > 0);
      },
      focusable: function () {
        return select.hidden ? words : select;
      }
    };
  }

  /** Choices and relations: the values, with their counts, in the editor. */
  function choicesField(controller, column, cell) {
    var wrap = el("div", "dt-filter-field dt-filter-field--choices");
    var picker = pickerButton(controller, column);

    wrap.appendChild(picker);
    cell.appendChild(wrap);

    return {
      control: picker,
      render: function () {
        var own = ownConditions(controller, column);

        picker.show(own);
        cell.classList.toggle("is-filtered", own.length > 0);
      },
      focusable: function () {
        return picker;
      }
    };
  }

  function buildField(controller, column, cell) {
    switch (query.kind(column)) {
      case "multiselect":
        return choicesField(controller, column, cell);
      case "boolean":
        return booleanField(controller, column, cell);
      default:
        return textField(controller, column, cell);
    }
  }

  /* -- The row ------------------------------------------------------------------ */

  function render(controller) {
    var row = controller.filterRow;

    row.fields.forEach(function (field) {
      field.render(row);
    });
  }

  function show(controller, shown, focus) {
    var row = controller.filterRow;

    row.shown = Boolean(shown);
    row.node.hidden = !row.shown;

    if (row.toggle) {
      row.toggle.classList.toggle("is-active", row.shown);
      row.toggle.setAttribute("aria-pressed", String(row.shown));
    }

    if (!focus) {
      return;
    }

    if (!row.shown) {
      if (row.toggle && row.node.contains(document.activeElement)) {
        row.toggle.focus();
      }

      return;
    }

    // The first field of a column on screen.
    for (var index = 0; index < row.fields.length; index += 1) {
      var target = row.fields[index].focusable();

      if (target.isConnected && target.offsetParent) {
        target.focus({ preventScroll: true });
        break;
      }
    }
  }

  function buildToggle(controller) {
    var label = t("Search by column");
    var toggle = el("button", "icon-button icon-button--sm dt-filter-row-toggle");

    toggle.type = "button";
    toggle.title = label;
    toggle.setAttribute("aria-label", label);
    toggle.appendChild(icon("manage_search", "icon--sm"));
    toggle.addEventListener("click", function () {
      controller.filterRow.chosen = true;
      show(controller, !controller.filterRow.shown, true);

      // Remembered with the rest of the layout, which DataTables
      // otherwise only saves when it draws.
      if (controller.instance && controller.instance.state) {
        controller.instance.state.save();
      }
    });

    return toggle;
  }

  core.registerFeature({
    name: "filterrow",

    enabled: function (controller) {
      return modeOf(controller) !== "";
    },

    header: function (controller, thead) {
      var node = thead.insertRow();
      var row = {
        node: node,
        fields: [],
        editing: null,
        toggle: null,
        chosen: false,
        shown: modeOf(controller) === OPEN
      };

      node.className = "dt-column-filters";
      // DataTables orders the table from a click in the header: not
      // from this row.
      node.setAttribute("data-dt-order", "disable");
      node.hidden = true;

      controller.columns.forEach(function (column) {
        var cell = document.createElement("td");

        cell.className = "dt-filter-cell";

        if (!column.synthetic && column.searchable !== false && query.keyOf(column)) {
          row.fields.push(buildField(controller, column, cell));
        }

        node.appendChild(cell);
      });

      controller.filterRow = row;
    },

    loadState: function (controller, data) {
      if (controller.filterRow && typeof data.genericFilterRow === "boolean") {
        controller.filterRow.shown = data.genericFilterRow;
        controller.filterRow.chosen = true;
      }
    },

    // Remembered only once the user has pressed the button: until then
    // the declaration decides, so a table someone merely looked at last
    // week still follows a `filter_row` changed since.
    saveState: function (controller, data) {
      if (controller.filterRow && controller.filterRow.chosen) {
        data.genericFilterRow = controller.filterRow.shown;
      } else {
        delete data.genericFilterRow;
      }
    },

    init: function (controller) {
      var row = controller.filterRow;
      var trigger = controller.filterTrigger;

      if (trigger && trigger.parentNode) {
        row.toggle = buildToggle(controller);
        trigger.parentNode.insertBefore(row.toggle, trigger.nextSibling);
      }

      controller.renderFilterRow = function () {
        render(controller);
      };

      controller.setFilterRow = function (shown) {
        show(controller, shown, false);
      };

      controller.listen(controller.table, "generic:filters-change", controller.renderFilterRow);

      show(controller, row.shown, false);
      render(controller);
    },

    // The row goes with the header, which a new start rebuilds; the
    // toggle sits in the toolbar, which DataTables leaves behind.
    destroy: function (controller) {
      if (controller.filterRow) {
        if (controller.filterRow.toggle) {
          controller.filterRow.toggle.remove();
        }

        controller.filterRow = null;
        controller.renderFilterRow = null;
      }
    }
  });

  namespace.filterrow = {
    readText: readText,
    textOf: textOf
  };
})(window, document);

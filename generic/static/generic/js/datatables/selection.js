/**
 * Row selection and bulk actions.
 *
 * The admin's action bar, over a server-side table: tick rows on this
 * page, or select every row the filters match - on every page - then
 * run an action on the server. "Every matching row" is sent as the
 * table's filters, not as a list of ids, so it means what is matched
 * when the action runs.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var el = core.el;
  var icon = core.icon;
  var t = core.t;

  function total(controller) {
    var info = controller.instance.page.info();

    return info ? info.recordsDisplay : 0;
  }

  function selectedCount(controller) {
    var selection = controller.selection;

    return selection.all ? total(controller) : selection.ids.size;
  }

  function run(controller, name) {
    var Generic = window.Generic;
    var actions = controller.options.bulkActions || [];
    var action = actions.find(function (entry) {
      return entry.name === name;
    });

    if (!action) {
      Generic.toast(t("Choose an action first."), "info");
      return;
    }

    var selection = controller.selection;
    var count = selectedCount(controller);

    var question = action.confirm
      ? Generic.dialogs.confirm({
          title: action.label,
          message:
            action.confirm +
            " " +
            core.format(t("(%(count)s row(s))"), { count: count }),
          confirmLabel: action.label,
          confirmIcon: action.icon,
          variant: action.variant === "danger" ? "danger" : "primary"
        })
      : Promise.resolve(true);

    question.then(function (confirmed) {
      if (!confirmed) {
        return;
      }

      var url = controller.options.bulkActionsUrl;
      var body = { action: name };

      if (selection.all) {
        body.all = true;
        url = Generic.api.buildUrl(url, controller.currentParams());
      } else {
        body.ids = Array.from(selection.ids.keys());
      }

      var apply = controller.slots.selection.apply;
      apply.disabled = true;

      Generic.api
        .post(url, body)
        .then(function (result) {
          var level = (result && result.level) || "success";

          Generic.toast((result && result.message) || t("Done."), level);

          if (level !== "error") {
            controller.clearSelection();
          }

          controller.reload(false);
        })
        .catch(function (error) {
          Generic.toast(error.message, "error");
        })
        .finally(function () {
          apply.disabled = false;
        });
    });
  }

  core.registerFeature({
    name: "selection",

    enabled: function (controller) {
      var options = controller.options;

      return Boolean(
        options.rowKey &&
          options.bulkActionsUrl &&
          (options.bulkActions || []).length
      );
    },

    prepare: function (controller) {
      var key = controller.options.rowKey;
      var header = el("input", "dt-check-all");

      header.type = "checkbox";
      header.setAttribute("aria-label", t("Select every row on this page"));

      controller.selection = { ids: new Map(), all: false, header: header };

      controller.columns.unshift({
        synthetic: "select",
        data: null,
        name: "",
        title: "",
        headerNode: header,
        orderable: false,
        searchable: false,
        visible: true,
        className: "dt-select",
        width: "2.75rem",
        defaultContent: "",
        render: function (data, type, row) {
          if (type !== "display") {
            return "";
          }

          var id = row[key];

          if (id === null || id === undefined) {
            return "";
          }

          return (
            '<input type="checkbox" class="dt-row-check" value="' +
            core.escapeHtml(String(id)) +
            '" aria-label="' +
            core.escapeHtml(t("Select this row")) +
            '">'
          );
        }
      });

      // The column went in first: a configured order points one further.
      if (Array.isArray(controller.options.order)) {
        controller.options.order = controller.options.order.map(function (entry) {
          return [entry[0] + 1, entry[1]];
        });
      }
    },

    top: function (controller) {
      var bar = el("div", "dt-selection-bar");
      var count = el("span", "dt-selection-bar__count");
      var across = el("button", "button--link dt-selection-bar__across");
      var select = el("select", "input input--sm dt-selection-bar__action");
      var apply = el("button", "button button--sm button--primary");
      var clear = el("button", "button button--sm button--ghost", t("Clear selection"));

      bar.hidden = true;
      bar.setAttribute("role", "region");
      bar.setAttribute("aria-label", t("Selected rows"));

      across.type = "button";
      apply.type = "button";
      clear.type = "button";

      select.setAttribute("aria-label", t("Action"));
      select.appendChild(new Option(t("Choose an action") + "\u2026", ""));

      controller.options.bulkActions.forEach(function (action) {
        select.appendChild(new Option(action.label, action.name));
      });

      apply.append(icon("play_arrow", "icon--sm"), document.createTextNode(t("Apply")));

      bar.append(
        icon("check_box"),
        count,
        across,
        el("span", "dt-selection-bar__spacer"),
        select,
        apply,
        clear
      );

      controller.slots.selection = {
        bar: bar,
        count: count,
        across: across,
        select: select,
        apply: apply,
        clear: clear
      };

      return bar;
    },

    init: function (controller) {
      var api = controller.instance;
      var key = controller.options.rowKey;
      var selection = controller.selection;
      var slots = controller.slots.selection;

      function pageRows() {
        return api.rows({ page: "current" }).data().toArray();
      }

      function render() {
        var count = selectedCount(controller);
        var rows = pageRows();
        var ids = rows.map(function (row) {
          return String(row[key]);
        });
        var checked = ids.filter(function (id) {
          return selection.all || selection.ids.has(id);
        }).length;
        var matching = total(controller);

        slots.bar.hidden = count === 0;
        slots.count.textContent = selection.all
          ? core.format(t("All %(count)s matching rows are selected."), { count: count })
          : core.format(t("%(count)s selected"), { count: count });

        // Offered once the whole page is ticked and there is more
        // beyond it - the admin's "Select all 312".
        slots.across.hidden =
          selection.all ||
          !ids.length ||
          checked !== ids.length ||
          matching <= ids.length;
        slots.across.textContent = core.format(
          t("Select all %(count)s matching rows"),
          { count: matching }
        );

        selection.header.checked = ids.length > 0 && checked === ids.length;
        selection.header.indeterminate = checked > 0 && checked < ids.length;

        controller.table.querySelectorAll("tbody .dt-row-check").forEach(function (box) {
          var on = selection.all || selection.ids.has(box.value);
          var row = box.closest("tr");

          box.checked = on;

          if (row) {
            row.classList.toggle("is-selected", on);
          }
        });
      }

      function clear() {
        selection.ids.clear();
        selection.all = false;
        render();
      }

      controller.clearSelection = clear;

      controller.table.addEventListener("change", function (event) {
        var box = event.target;

        if (!box.classList || !box.classList.contains("dt-row-check")) {
          return;
        }

        // Unticking one row out of "every matching row" turns the
        // selection back into the rows on this page, minus that one.
        if (selection.all) {
          selection.all = false;
          pageRows().forEach(function (row) {
            selection.ids.set(String(row[key]), row);
          });
        }

        if (box.checked) {
          selection.ids.set(box.value, api.row(box.closest("tr")).data());
        } else {
          selection.ids.delete(box.value);
        }

        render();
      });

      // The checkbox sits in a header cell; a click must not sort.
      selection.header.addEventListener("click", function (event) {
        event.stopPropagation();
      });

      selection.header.addEventListener("change", function () {
        if (selection.all && !selection.header.checked) {
          clear();
          return;
        }

        pageRows().forEach(function (row) {
          var id = String(row[key]);

          if (selection.header.checked) {
            selection.ids.set(id, row);
          } else {
            selection.ids.delete(id);
          }
        });

        render();
      });

      slots.across.addEventListener("click", function () {
        selection.all = true;
        render();
      });

      slots.clear.addEventListener("click", clear);

      slots.apply.addEventListener("click", function () {
        run(controller, slots.select.value);
      });

      api.on("draw", render);
    }
  });
})(window, document);

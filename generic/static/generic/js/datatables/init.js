/**
 * Finds the tables on the page and starts them.
 *
 * Two configuration shapes are accepted:
 *
 *   data-config="element-id"   one JSON script holding
 *                              {url, columns, options} - what
 *                              DataTableView emits
 *
 *   data-url + data-columns-id + data-options-id
 *                              the older split form
 *
 * A failure is reported in `#datatable-error` rather than left as an
 * empty table with no explanation.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var GenericDataTable = namespace.GenericDataTable;

  function showError(message) {
    var box = document.getElementById("datatable-error");

    if (!box) {
      window.console.error(message);
      return;
    }

    box.textContent = message;
    box.hidden = false;
  }

  function readConfig(table) {
    var id = table.dataset.config;

    if (!id) {
      return null;
    }

    var config = core.readJsonScript(id, null);

    if (!config) {
      return null;
    }

    return Object.assign({}, config.options || {}, {
      url: config.url,
      columns: config.columns
    });
  }

  function start(table) {
    if (table.dataset.genericDatatableReady === "true") {
      return null;
    }

    if (typeof window.DataTable !== "function") {
      showError(
        core.t(
          "DataTables is not loaded. Add it to the datatable_vendor block."
        )
      );
      return null;
    }

    table.dataset.genericDatatableReady = "true";

    try {
      var controller = new GenericDataTable(table, readConfig(table) || {});
      table.genericDataTable = controller;

      return controller;
    } catch (error) {
      table.dataset.genericDatatableReady = "false";
      showError(
        core.t("The table could not be initialised.") + " " + error.message
      );
      window.console.error(error);

      table.dispatchEvent(
        new CustomEvent("generic:datatable-error", {
          bubbles: true,
          detail: { error: error }
        })
      );

      return null;
    }
  }

  function initialize(root) {
    var controllers = [];

    (root || document)
      .querySelectorAll(core.DEFAULTS.selector)
      .forEach(function (table) {
        var controller = start(table);

        if (controller) {
          controllers.push(controller);
        }
      });

    return controllers;
  }

  // A request rejected after the table was built reports through an
  // event; surface that in the same place as a start-up failure.
  document.addEventListener("generic:datatable-error", function (event) {
    if (event.detail && event.detail.message) {
      showError(event.detail.message);
    }
  });

  namespace.initialize = initialize;

  // Kept as the documented entry point, and for pages that build a
  // table by hand rather than from markup.
  window.DrfDataTable = GenericDataTable;
  window.GenericDataTables.start = start;

  // Scripts deferred before this one (a summary page's tabs, started
  // by Alpine) may ask for a table before `start` exists: they wait
  // for this.
  document.dispatchEvent(new window.CustomEvent("generic:datatables-loaded"));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initialize(document);
    });
  } else {
    initialize(document);
  }
})(window, document);

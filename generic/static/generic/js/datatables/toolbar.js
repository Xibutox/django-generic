/**
 * The band above a table: search, filters, saved views, columns,
 * exports and a reload button.
 *
 * genericOLD's top menu, rebuilt. The same tools, with icons where the
 * old one had emoji; exports done by the server, so a file holds every
 * matching row rather than the page on screen; and a user's views
 * saved on their account instead of in one browser.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var el = core.el;
  var icon = core.icon;
  var t = core.t;

  function generic() {
    return window.Generic || null;
  }

  /* -- Building blocks ---------------------------------------------------- */

  function toolButton(iconName, label) {
    var button = el("button", "button button--sm dt-tool");

    button.type = "button";
    button.title = label;
    button.append(icon(iconName, "icon--sm"), el("span", "dt-tool__label", label));

    return button;
  }

  function menuItem(iconName, label, hint) {
    var item = el("button", "menu-item");

    item.type = "button";
    item.append(icon(iconName), el("span", "menu-item__label", label));

    if (hint) {
      item.appendChild(el("span", "menu-item__hint", hint));
    }

    return item;
  }

  function smallIconButton(iconName, label, extra) {
    var button = el("button", "icon-button icon-button--sm");

    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(icon(iconName, "icon--sm" + (extra ? " " + extra : "")));

    return button;
  }

  /**
   * A menu anchored to a toolbar button. Opening one closes the others;
   * a click elsewhere or Escape closes it.
   */
  function createMenu(controller, iconName, label, panelClass) {
    var root = el("div", "dropdown dt-menu");
    var trigger = toolButton(iconName, label);
    var panel = el(
      "div",
      "dropdown__menu dt-menu__panel" + (panelClass ? " " + panelClass : "")
    );
    var menu = { root: root, trigger: trigger, panel: panel, onOpen: null };

    trigger.setAttribute("aria-haspopup", "true");
    trigger.setAttribute("aria-expanded", "false");
    panel.hidden = true;
    root.append(trigger, panel);

    menu.open = function () {
      document.querySelectorAll(".dt-menu__panel").forEach(function (other) {
        if (other !== panel && !other.hidden) {
          other.hidden = true;

          if (other.previousElementSibling) {
            other.previousElementSibling.setAttribute("aria-expanded", "false");
          }
        }
      });

      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");

      if (menu.onOpen) {
        menu.onOpen();
      }
    };

    menu.close = function () {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    };

    trigger.addEventListener("click", function (event) {
      event.stopPropagation();

      if (panel.hidden) {
        menu.open();
      } else {
        menu.close();
      }
    });

    panel.addEventListener("click", function (event) {
      event.stopPropagation();
    });

    root.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        menu.close();
        trigger.focus();
      }
    });

    controller.listen(document, "click", menu.close);

    return menu;
  }

  /* -- Search ----------------------------------------------------------- */

  function buildSearch(controller) {
    // Not "dt-search": DataTables' own stylesheet styles that class.
    var box = el("label", "dt-toolbar__search input-with-icon");
    var input = el("input", "input input--sm");

    input.type = "search";
    input.placeholder = t("Search") + "\u2026";
    input.setAttribute("aria-label", t("Search every column"));
    input.title = t(
      "Every word must match. Put ! before a word to exclude it, and " +
        "quotes around a phrase."
    );

    box.append(icon("search", "icon--sm"), input);
    controller.searchInput = input;

    return box;
  }

  function bindSearch(controller) {
    var input = controller.searchInput;

    if (!input) {
      return;
    }

    var box = input.parentNode;

    function sync() {
      box.classList.toggle("has-value", Boolean(input.value));
    }

    // The words typed, without the `name:value` filters among them
    // (filterbar.js turns those into filters).
    function text() {
      return controller.freeSearchText
        ? controller.freeSearchText(input.value)
        : input.value.trim();
    }

    var run = core.debounce(function () {
      var value = text();

      if (value !== (controller.instance.search() || "")) {
        controller.instance.search(value);
        controller.redraw();
      }
    }, controller.options.searchDelay);

    input.value = controller.instance.search() || "";
    sync();

    input.addEventListener("input", function () {
      sync();
      run();
    });

    // Sent by the controller after it changed the value itself.
    input.addEventListener("generic:sync", sync);

    input.addEventListener("keydown", function (event) {
      if (controller.onSearchKeydown && controller.onSearchKeydown(event)) {
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        controller.instance.search(text());
        controller.redraw();
      }
    });
  }

  /* -- Views -------------------------------------------------------------
   *
   * A view is a whole layout: visible columns, sorting, filters, search
   * and page length. Suggested views come from the resource; a user's
   * own are saved through the API.
   */

  function buildViews(controller) {
    var presets = controller.options.presets || {};
    var url = controller.options.savedViewsUrl;

    if (!Object.keys(presets).length && !(url && generic())) {
      return null;
    }

    var menu = createMenu(controller, "bookmarks", t("Views"), "dt-views-panel");
    var label = menu.trigger.querySelector(".dt-tool__label");

    controller.activeView = "";
    controller.setActiveView = function (name) {
      controller.activeView = name || "";
      label.textContent = name || t("Views");
      menu.trigger.classList.toggle("is-active", Boolean(name));
    };

    menu.onOpen = function () {
      renderViews(controller, menu);
    };

    return menu.root;
  }

  function renderViews(controller, menu) {
    var Generic = generic();
    var panel = menu.panel;
    var presets = controller.options.presets || {};
    var names = Object.keys(presets);
    var url = controller.options.savedViewsUrl;

    panel.replaceChildren();

    if (names.length) {
      panel.appendChild(el("div", "dropdown__label", t("Suggested")));

      names.forEach(function (name) {
        var item = menuItem("view_quilt", name);

        item.classList.toggle("is-selected", controller.activeView === name);
        item.addEventListener("click", function () {
          controller.applyState(presets[name]);
          controller.setActiveView(name);
          menu.close();
        });
        panel.appendChild(item);
      });
    }

    if (url && Generic) {
      panel.appendChild(el("div", "dropdown__label", t("My views")));

      var list = el("div", "dt-views");
      list.appendChild(el("div", "dt-views__empty", t("Loading") + "\u2026"));
      panel.appendChild(list);

      Generic.api
        .get(url, { table: controller.options.stateKey })
        .then(function (rows) {
          rows = Array.isArray(rows) ? rows : (rows && rows.results) || [];
          list.replaceChildren();

          if (!rows.length) {
            list.appendChild(
              el("div", "dt-views__empty", t("Nothing saved yet."))
            );
          }

          rows.forEach(function (view) {
            list.appendChild(renderView(controller, menu, view));
          });
        })
        .catch(function (error) {
          list.replaceChildren(el("div", "dt-views__empty", error.message));
        });
    }

    panel.appendChild(el("div", "dropdown__divider"));

    if (url && Generic) {
      var save = menuItem("bookmark_add", t("Save this view") + "\u2026");

      save.addEventListener("click", function () {
        menu.close();
        saveView(controller);
      });
      panel.appendChild(save);
    }

    var reset = menuItem("restart_alt", t("Back to the default layout"));

    reset.addEventListener("click", function () {
      controller.resetLayout();
      controller.setActiveView("");
      menu.close();
    });
    panel.appendChild(reset);
  }

  function renderView(controller, menu, view) {
    var Generic = generic();
    var url = controller.options.savedViewsUrl;
    var row = el("div", "dt-view");
    var apply = el("button", "menu-item dt-view__apply");

    apply.type = "button";
    apply.append(
      icon("bookmark"),
      el("span", "menu-item__label", view.name)
    );
    apply.classList.toggle("is-selected", controller.activeView === view.name);
    apply.addEventListener("click", function () {
      controller.applyState(view.state);
      controller.setActiveView(view.name);
      menu.close();
    });

    var star = smallIconButton(
      "star",
      view.is_default
        ? t("Opens with this view")
        : t("Open the table with this view"),
      view.is_default ? "is-filled" : ""
    );

    star.classList.toggle("is-active", Boolean(view.is_default));
    star.addEventListener("click", function () {
      Generic.api
        .patch(url + view.id + "/", { is_default: !view.is_default })
        .then(function () {
          renderViews(controller, menu);
        })
        .catch(function (error) {
          Generic.toast(error.message, "error");
        });
    });

    var remove = smallIconButton("delete", t("Delete this view"));

    remove.addEventListener("click", function () {
      Generic.dialogs
        .confirm({
          title: t("Delete this view?"),
          message: view.name,
          confirmLabel: t("Delete"),
          variant: "danger"
        })
        .then(function (confirmed) {
          if (!confirmed) {
            return;
          }

          Generic.api
            .delete(url + view.id + "/")
            .then(function () {
              if (controller.activeView === view.name) {
                controller.setActiveView("");
              }

              renderViews(controller, menu);
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
            });
        });
    });

    row.append(apply, star, remove);

    return row;
  }

  function saveView(controller) {
    var Generic = generic();

    Generic.dialogs
      .prompt({
        title: t("Save this view"),
        icon: "bookmark_add",
        label: t("Name"),
        value: controller.activeView || "",
        placeholder: t("Open tickets this week"),
        confirmLabel: t("Save"),
        checkbox: { label: t("Open the table with this view"), checked: false }
      })
      .then(function (result) {
        if (!result) {
          return;
        }

        Generic.api
          .post(controller.options.savedViewsUrl, {
            table: controller.options.stateKey,
            name: result.value,
            state: controller.captureState(),
            is_default: result.checked
          })
          .then(function () {
            controller.setActiveView(result.value);
            Generic.toast(
              core.format(t("View \u201c%(name)s\u201d saved."), { name: result.value }),
              "success"
            );
          })
          .catch(function (error) {
            Generic.toast(error.message, "error");
          });
      });
  }

  /**
   * A view marked as default opens with the table - unless the table
   * is coming back from a state of its own, which the user left it in.
   */
  function applyDefaultView(controller) {
    var Generic = generic();
    var url = controller.options.savedViewsUrl;

    if (!url || !Generic || controller.restoredState) {
      return;
    }

    Generic.api
      .get(url, { table: controller.options.stateKey })
      .then(function (rows) {
        rows = Array.isArray(rows) ? rows : [];

        var view = rows.find(function (entry) {
          return entry.is_default;
        });

        if (view) {
          controller.applyState(view.state);
          controller.setActiveView(view.name);
        }
      })
      .catch(function () {
        /* The declared layout stays. */
      });
  }

  /* -- Columns ---------------------------------------------------------- */

  function buildColumns(controller) {
    var menu = createMenu(
      controller,
      "view_column",
      controller.options.columnSelectorLabel || t("Columns"),
      "dt-columns"
    );
    var panel = menu.panel;
    var search = el("input", "input input--sm dt-columns__search");
    var list = el("div", "dt-columns__list");

    search.type = "search";
    search.placeholder = t("Find a column") + "\u2026";
    search.setAttribute("aria-label", t("Find a column"));

    controller.dataColumns().forEach(function (entry) {
      var option = el("label", "dt-colvis-option");
      var checkbox = el("input");

      checkbox.type = "checkbox";
      checkbox.checked = entry.column.visible !== false;
      checkbox.dataset.columnIndex = String(entry.index);
      checkbox.addEventListener("change", function () {
        controller.instance.column(entry.index).visible(checkbox.checked);
        controller.instance.columns.adjust();
      });

      option.dataset.search = String(entry.column.title || "").toLowerCase();
      option.append(checkbox, document.createTextNode(entry.column.title));
      list.appendChild(option);
    });

    search.addEventListener("input", function () {
      var query = search.value.trim().toLowerCase();

      list.querySelectorAll(".dt-colvis-option").forEach(function (option) {
        option.hidden = Boolean(query) && option.dataset.search.indexOf(query) === -1;
      });
    });

    var actions = el("div", "dt-columns__actions");
    var showAll = el("button", "button button--sm button--ghost", t("Show all"));
    var restore = el("button", "button button--sm button--ghost", t("Default"));

    showAll.type = "button";
    restore.type = "button";

    showAll.addEventListener("click", function () {
      controller.dataColumns().forEach(function (entry) {
        controller.instance.column(entry.index).visible(true, false);
      });
      controller.instance.columns.adjust().draw(false);
    });

    restore.addEventListener("click", function () {
      controller.dataColumns().forEach(function (entry) {
        controller.instance
          .column(entry.index)
          .visible(controller.defaultVisibility[entry.index], false);
      });
      controller.instance.columns.adjust().draw(false);
    });

    actions.append(showAll, restore);
    panel.append(search, list, actions);

    menu.onOpen = function () {
      search.focus();
    };

    controller.columnSelector = menu.root;
    controller.syncColumnSelector = function () {
      var api = controller.instance;

      list.querySelectorAll("input[data-column-index]").forEach(function (checkbox) {
        checkbox.checked = api.column(Number(checkbox.dataset.columnIndex)).visible();
      });

      var changed = controller.dataColumns().some(function (entry) {
        return api.column(entry.index).visible() !== controller.defaultVisibility[entry.index];
      });

      menu.trigger.classList.toggle("is-active", changed);
    };

    return menu.root;
  }

  /* -- Export ----------------------------------------------------------- */

  function buildExport(controller) {
    var options = controller.options;

    if (!options.excel && !options.csv && !options.copy && !options.print) {
      return null;
    }

    var menu = createMenu(controller, "download", t("Export"), "dt-export-panel");
    var panel = menu.panel;

    function add(iconName, label, hint, action) {
      var item = menuItem(iconName, label, hint);

      item.addEventListener("click", function () {
        menu.close();
        action();
      });
      panel.appendChild(item);
    }

    if (options.excel || options.csv) {
      panel.appendChild(el("div", "dropdown__label", t("Every matching row")));
    }

    if (options.excel) {
      add("table_view", t("Excel"), ".xlsx", function () {
        controller.download("export");
      });
    }

    if (options.csv) {
      add("description", t("CSV"), ".csv", function () {
        controller.download("export-csv");
      });
    }

    if ((options.excel || options.csv) && (options.copy || options.print)) {
      panel.appendChild(el("div", "dropdown__divider"));
    }

    if (options.copy || options.print) {
      panel.appendChild(el("div", "dropdown__label", t("This page")));
    }

    if (options.copy) {
      add("content_copy", t("Copy to the clipboard"), "", function () {
        controller.copyPage();
      });
    }

    if (options.print) {
      add("print", t("Print"), "", function () {
        controller.printPage();
      });
    }

    return menu.root;
  }

  /* -- The feature --------------------------------------------------------- */

  core.registerFeature({
    name: "toolbar",

    top: function (controller) {
      var bar = el("div", "dt-toolbar");
      var tools = el("div", "dt-toolbar__tools");

      // Where another feature puts a button of its own: the grid's
      // "Add a row" goes first in it.
      controller.slots.tools = tools;
      bar.appendChild(buildSearch(controller));

      if (controller.options.filters && namespace.filterbar) {
        tools.appendChild(namespace.filterbar.buildTools(controller));
      }

      [
        buildViews,
        controller.options.columnSelector ? buildColumns : null,
        buildExport
      ].forEach(function (build) {
        var node = build ? build(controller) : null;

        if (node) {
          tools.appendChild(node);
        }
      });

      var reload = smallIconButton("refresh", t("Reload the rows"));

      reload.classList.remove("icon-button--sm");
      reload.addEventListener("click", function () {
        controller.reload(false);
      });
      tools.appendChild(reload);

      bar.appendChild(tools);

      return bar;
    },

    init: function (controller) {
      var api = controller.instance;

      bindSearch(controller);

      if (controller.updateFilterCount) {
        api.on("draw", controller.updateFilterCount);
        controller.updateFilterCount();
      }

      if (controller.syncColumnSelector) {
        api.on("column-visibility", controller.syncColumnSelector);
        controller.syncColumnSelector();
      }

      applyDefaultView(controller);
    }
  });
})(window, document);

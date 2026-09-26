/**
 * What can be done with one row: a menu at the end of the row, the
 * same menu on a right click, and a double click to open it.
 *
 * genericOLD's context menu, without the jQuery plugin behind it. The
 * actions come from the resource, already filtered on the user's
 * permissions: open the record, delete it through the same preview
 * dialog the change page uses.
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var el = core.el;
  var icon = core.icon;
  var t = core.t;

  function rowLabel(controller, row) {
    if (row._label) {
      return String(row._label);
    }

    var first = controller.dataColumns()[0];

    return first ? controller.cellText(first.column, row) : "";
  }

  function closeMenu(controller) {
    if (controller.rowMenu) {
      controller.rowMenu.hidden = true;
    }
  }

  function deleteRow(controller, action, row) {
    var Generic = window.Generic;
    var label = rowLabel(controller, row);

    Generic.dialogs
      .deletion({
        previewUrl: core.fillTemplate(action.previewUrl, row),
        deleteUrl: core.fillTemplate(action.apiUrl, row),
        label: label
      })
      .then(function (deleted) {
        if (!deleted) {
          return;
        }

        Generic.toast(
          core.format(t("\u201c%(name)s\u201d was deleted."), { name: label }),
          "success"
        );
        controller.reload(false);
      });
  }

  /**
   * Open the menu for `row` at a point of the viewport. `alignRight`
   * lines its right edge up with the point instead of its left.
   */
  function openMenu(controller, row, x, y, alignRight, filters) {
    var Generic = window.Generic;
    var menu = controller.rowMenu;

    menu.replaceChildren();

    // A right click on a cell starts with filters on its value.
    if (filters && filters.length) {
      menu.appendChild(el("div", "dropdown__label", t("Filter on this value")));

      filters.forEach(function (entry) {
        var item = el("button", "menu-item");

        item.type = "button";
        item.setAttribute("role", "menuitem");
        item.append(icon(entry.icon), el("span", "menu-item__label", entry.label));
        item.addEventListener("click", function () {
          closeMenu(controller);
          entry.run();
        });
        menu.appendChild(item);
      });

      if (controller.options.rowActions.length) {
        menu.appendChild(el("div", "dropdown__divider"));
      }
    }

    controller.options.rowActions.forEach(function (action) {
      if (action.url) {
        var url = core.fillTemplate(action.url, row);

        if (!url) {
          return;
        }

        var link = el("a", "menu-item");
        link.href = url;
        link.setAttribute("role", "menuitem");
        link.append(
          icon(action.icon || "arrow_forward"),
          el("span", "menu-item__label", action.label)
        );
        menu.appendChild(link);
        return;
      }

      if (action.apiUrl && Generic && Generic.dialogs) {
        var button = el(
          "button",
          "menu-item" + (action.variant === "danger" ? " menu-item--danger" : "")
        );

        button.type = "button";
        button.setAttribute("role", "menuitem");
        button.append(
          icon(action.icon || "bolt"),
          el("span", "menu-item__label", action.label)
        );
        button.addEventListener("click", function () {
          closeMenu(controller);
          deleteRow(controller, action, row);
        });
        menu.appendChild(button);
      }
    });

    if (!menu.childNodes.length) {
      return;
    }

    menu.hidden = false;

    var width = menu.offsetWidth || 200;
    var height = menu.offsetHeight || 120;
    var left = alignRight ? x - width : x;

    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));

    var top = y + height > window.innerHeight - 8 ? Math.max(8, y - height) : y;

    menu.style.left = left + "px";
    menu.style.top = top + "px";

    var first = menu.querySelector(".menu-item");

    if (first) {
      first.focus();
    }
  }

  core.registerFeature({
    name: "rowActions",

    enabled: function (controller) {
      return Boolean((controller.options.rowActions || []).length);
    },

    prepare: function (controller) {
      controller.columns.push({
        synthetic: "actions",
        data: null,
        name: "",
        title: "",
        orderable: false,
        searchable: false,
        visible: true,
        className: "dt-row-actions",
        width: "3rem",
        defaultContent: "",
        render: function (data, type) {
          if (type !== "display") {
            return "";
          }

          return (
            '<button type="button" class="icon-button icon-button--sm dt-row-menu" ' +
            'aria-haspopup="menu" aria-label="' +
            core.escapeHtml(t("Actions")) +
            '"><span class="icon material-symbols-outlined" aria-hidden="true">' +
            "more_vert</span></button>"
          );
        }
      });
    },

    init: function (controller) {
      var api = controller.instance;
      var menu = el("div", "dropdown__menu dt-row-popover");

      menu.setAttribute("role", "menu");
      menu.hidden = true;
      document.body.appendChild(menu);
      controller.rowMenu = menu;

      function rowAt(target) {
        var tr = target.closest("tbody tr");

        if (!tr || !controller.table.contains(tr)) {
          return null;
        }

        var data = api.row(tr).data();

        return data ? { tr: tr, data: data } : null;
      }

      controller.table.addEventListener("click", function (event) {
        var trigger = event.target.closest(".dt-row-menu");

        if (!trigger) {
          return;
        }

        event.stopPropagation();

        var found = rowAt(trigger);

        if (found) {
          var rect = trigger.getBoundingClientRect();
          openMenu(controller, found.data, rect.right, rect.bottom + 4, true);
        }
      });

      // Controls keep the browser's own menu. A link gets ours - most
      // relation cells are links, and filtering on them is the point -
      // with "open in a new tab" added; Shift keeps the browser's.
      controller.table.addEventListener("contextmenu", function (event) {
        if (event.shiftKey || event.target.closest("input, select, textarea, thead")) {
          return;
        }

        var found = rowAt(event.target);

        if (found) {
          var cell = event.target.closest("td");
          var index = cell ? api.cell(cell).index() : null;
          var link = event.target.closest("a[href]");
          var filters =
            index && namespace.filterbar && controller.filterTree
              ? namespace.filterbar.quickFilters(
                  controller,
                  controller.columns[index.column],
                  found.data,
                  event.target
                )
              : [];

          if (link && !filters.length) {
            return;
          }

          if (link && core.isSafeUrl(link.getAttribute("href"))) {
            filters.push({
              icon: "open_in_new",
              label: t("Open the link in a new tab"),
              run: function () {
                window.open(link.href, "_blank", "noopener");
              }
            });
          }

          event.preventDefault();
          openMenu(controller, found.data, event.clientX, event.clientY, false, filters);
        }
      });

      controller.table.addEventListener("dblclick", function (event) {
        if (event.target.closest("a, input, select, textarea, button, label, thead")) {
          return;
        }

        var found = rowAt(event.target);
        var open = controller.options.rowActions.find(function (action) {
          return action.url;
        });

        if (found && open) {
          var url = core.fillTemplate(open.url, found.data);

          if (url) {
            window.location.assign(url);
          }
        }
      });

      menu.addEventListener("click", function (event) {
        event.stopPropagation();
      });

      controller.listen(document, "click", function () {
        closeMenu(controller);
      });

      controller.listen(document, "keydown", function (event) {
        if (event.key === "Escape") {
          closeMenu(controller);
        }
      });

      controller.listen(
        window,
        "scroll",
        function () {
          closeMenu(controller);
        },
        true
      );

      controller.listen(window, "resize", function () {
        closeMenu(controller);
      });
    },

    destroy: function (controller) {
      if (controller.rowMenu) {
        controller.rowMenu.remove();
        controller.rowMenu = null;
      }
    }
  });
})(window, document);

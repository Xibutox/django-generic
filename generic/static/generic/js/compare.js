/**
 * Records side by side (generic.sites.compare): a column per record, a
 * row per field, the rows whose values differ marked, and a switch
 * hiding the others.
 *
 * The page's address names the records (?ids=3,8,12); removing one
 * keeps the address in step, so a comparison can be bookmarked.
 *
 *   <div class="generic-compare" data-config="<id of a json_script>"></div>
 *   Generic.compare.start(element)
 *
 * Every value reaches the page through textContent (Generic.values),
 * every address through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var values = Generic.values;
  var el = values.el;
  var icon = values.icon;

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

  function splitIds(text) {
    return String(text || "")
      .split(",")
      .map(function (piece) {
        return piece.trim();
      })
      .filter(Boolean);
  }

  function CompareView(element, config) {
    this.element = element;
    this.config = config;
    this.ids = splitIds(config.ids);
    this.answer = null;
    this.build();
  }

  CompareView.prototype.build = function () {
    var self = this;
    var toolbar = el("div", "compare__toolbar");
    var label = el("label", "switch compare__only");

    this.only = el("input");
    this.only.type = "checkbox";
    this.only.addEventListener("change", function () {
      self.element.classList.toggle("is-differences-only", self.only.checked);
    });
    label.appendChild(this.only);
    label.appendChild(el("span", "", t("Only the differences")));

    this.status = el("span", "compare__status muted");
    this.status.setAttribute("aria-live", "polite");

    toolbar.appendChild(this.status);
    toolbar.appendChild(label);

    this.body = el("div", "compare__body");
    this.element.textContent = "";
    this.element.appendChild(toolbar);
    this.element.appendChild(this.body);
  };

  CompareView.prototype.refresh = function () {
    var self = this;

    this.status.textContent = t("Loading\u2026");

    return Generic.api
      .get(this.config.url, { ids: this.ids.join(",") })
      .then(function (answer) {
        self.answer = answer;
        self.draw();
      })
      .catch(function (error) {
        self.status.textContent = "";
        self.body.textContent = "";
        self.body.appendChild(
          el("p", "compare__message", (error && error.message) || t("These records could not be compared."))
        );
        self.body.appendChild(self.backLink());
      });
  };

  CompareView.prototype.backLink = function () {
    var link = values.link(this.config.listUrl, t("Back to the list"));

    link.classList.add("button", "button--sm");

    return link;
  };

  CompareView.prototype.draw = function () {
    var answer = this.answer || {};
    var records = answer.records || [];
    var differing = 0;

    this.body.textContent = "";

    (answer.sections || []).forEach(function (section) {
      (section.rows || []).forEach(function (row) {
        if (!row.same) {
          differing += 1;
        }
      });
    });

    this.status.textContent = Generic.format(
      Generic.nt("%(count)s field differs", "%(count)s fields differ", differing),
      { count: differing }
    );

    if (answer.missing) {
      this.body.appendChild(
        el(
          "p",
          "compare__message muted",
          Generic.format(
            Generic.nt(
              "%(count)s record could not be shown: it is not there, or not yours to see.",
              "%(count)s records could not be shown: they are not there, or not yours to see.",
              answer.missing
            ),
            { count: answer.missing }
          )
        )
      );
    }

    if (records.length < 2) {
      this.body.appendChild(el("p", "compare__message", t("Two records at least are needed to compare.")));
      this.body.appendChild(this.backLink());
      return;
    }

    var scroller = el("div", "compare__scroll");

    scroller.appendChild(this.drawTable(answer, records));
    this.body.appendChild(scroller);
  };

  CompareView.prototype.drawTable = function (answer, records) {
    var self = this;
    var table = el("table", "compare-table");
    var head = el("thead");
    var top = el("tr");
    var corner = el("th", "compare-table__corner", t("Field"));

    corner.scope = "col";
    top.appendChild(corner);

    records.forEach(function (record) {
      var cell = el("th", "compare-table__record");
      var label = values.link(record.url, record.label);

      cell.scope = "col";
      cell.appendChild(label);

      if (records.length > 2) {
        cell.appendChild(self.removeButton(record));
      }

      top.appendChild(cell);
    });

    head.appendChild(top);
    table.appendChild(head);

    (answer.sections || []).forEach(function (section) {
      var body = el("tbody", "compare-table__section");

      if (section.title) {
        var titleRow = el("tr", "compare-table__title");
        var title = el("th", "", section.title);

        title.colSpan = records.length + 1;
        title.scope = "colgroup";
        titleRow.appendChild(title);
        body.appendChild(titleRow);
      }

      (section.rows || []).forEach(function (row) {
        body.appendChild(self.drawRow(row));
      });

      table.appendChild(body);
    });

    return table;
  };

  CompareView.prototype.drawRow = function (row) {
    var tr = el("tr", "compare-row" + (row.same ? " is-same" : " is-different"));
    var name = el("th", "compare-row__label", row.label);

    name.scope = "row";

    if (!row.same) {
      name.appendChild(el("span", "sr-only", " " + t("(differs)")));
    }

    tr.appendChild(name);

    (row.values || []).forEach(function (entry) {
      var cell = el("td", "compare-row__value");

      cell.appendChild(values.render(entry));
      tr.appendChild(cell);
    });

    return tr;
  };

  CompareView.prototype.removeButton = function (record) {
    var self = this;
    var button = el("button", "icon-button icon-button--sm compare-table__remove");
    var label = Generic.format(t("Remove %(label)s from the comparison"), { label: record.label });

    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(icon("close"));
    button.addEventListener("click", function () {
      self.ids = self.ids.filter(function (id) {
        return id !== String(record.id);
      });
      self.keepAddress();
      self.refresh();
    });

    return button;
  };

  /** The address names the records still compared. */
  CompareView.prototype.keepAddress = function () {
    var query = "?ids=" + this.ids.map(encodeURIComponent).join(",");

    window.history.replaceState(window.history.state, "", window.location.pathname + query);
  };

  function start(element) {
    if (!element || element.genericCompare) {
      return element && element.genericCompare;
    }

    var config = readJson(element.getAttribute("data-config"));

    if (!config || !config.url) {
      return null;
    }

    var view = new CompareView(element, config);

    element.genericCompare = view;
    view.refresh();

    return view;
  }

  Generic.compare = { start: start };

  Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".generic-compare[data-autostart]"), start);
  });
})(window, document);

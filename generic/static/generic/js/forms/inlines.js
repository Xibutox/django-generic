/**
 * Inlines: the related rows edited on their parent's form.
 *
 * Two presentations of the same controller. "tabular" draws one table
 * row per record, for a few short fields; "stacked" one card per
 * record, laid out like the main form.
 *
 * Only what changed travels on an update: new rows, edited rows and
 * rows marked for deletion. The server answers errors by position in
 * that list, which is why the controller remembers which row it sent
 * at each position.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var forms = Generic.forms;

  var counter = 0;

  function el(tag, className, text) {
    var node = document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (text !== undefined && text !== null) {
      node.textContent = text;
    }

    return node;
  }

  function icon(name, extra) {
    var node = el("span", "icon material-symbols-outlined" + (extra ? " " + extra : ""), name);
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  function same(first, second) {
    return JSON.stringify(first) === JSON.stringify(second);
  }

  function messagesOf(value) {
    if (value === null || value === undefined) {
      return [];
    }

    if (Array.isArray(value)) {
      return value.reduce(function (all, item) {
        return all.concat(typeof item === "string" ? [item] : messagesOf(item));
      }, []);
    }

    if (typeof value === "object") {
      return Object.keys(value).reduce(function (all, key) {
        return all.concat(messagesOf(value[key]));
      }, []);
    }

    return [String(value)];
  }

  function Inline(definition, form) {
    this.definition = definition;
    this.form = form;
    this.rows = [];
    this.sentRows = [];
    this.readOnly = Boolean(form.readOnly || definition.readOnly);
    this.tabular = definition.presentation !== "stacked";
    this.build();
  }

  Inline.prototype.fields = function () {
    // A row's own key travels as row.primaryKey, not as a cell.
    return (this.definition.fields || []).filter(function (field) {
      return !field.hidden;
    });
  };

  /* -- Frame -------------------------------------------------------------- */

  Inline.prototype.build = function () {
    var self = this;
    var definition = this.definition;
    var root = el("section", "inline-group");
    root.dataset.inline = definition.name;

    var header = el("div", "inline-group__header");
    var text = el("div");
    var title = el("h2", "inline-group__title");
    title.append(icon(this.tabular ? "table_rows" : "view_agenda"), document.createTextNode(definition.title || definition.name));
    this.count = el("span", "badge");
    title.appendChild(this.count);
    text.appendChild(title);

    if (definition.description) {
      text.appendChild(el("p", "inline-group__description", definition.description));
    }

    header.appendChild(text);

    this.errors = el("div", "inline-group__errors");
    this.errors.setAttribute("role", "alert");

    if (this.tabular) {
      var wrapper = el("div", "inline-table-wrapper");
      var table = el("table", "inline-table");
      var head = el("thead");
      var headRow = el("tr");

      this.fields().forEach(function (field) {
        var cell = el("th", "", field.label || field.name);
        cell.scope = "col";

        if (field.required && !field.readOnly && !self.readOnly) {
          var star = el("span", "sf-required", "*");
          star.setAttribute("aria-hidden", "true");
          cell.appendChild(star);
        }

        if (field.helpText) {
          cell.title = field.helpText;
        }

        headRow.appendChild(cell);
      });

      headRow.appendChild(el("th", "inline-table__actions"));
      head.appendChild(headRow);

      this.body = el("tbody");
      table.append(head, this.body);
      wrapper.appendChild(table);
      this.container = wrapper;
    } else {
      this.body = el("div", "inline-stack");
      this.container = this.body;
    }

    this.empty = el("div", "inline-empty", t("Nothing here yet."));

    var footer = el("div", "inline-group__footer");
    this.hint = el("span");

    if (!this.readOnly && definition.canAdd) {
      this.addButton = el("button", "button button--sm");
      this.addButton.type = "button";
      this.addButton.append(
        icon("add"),
        document.createTextNode(
          definition.addLabel ||
            Generic.format(t("Add another %(name)s"), {
              name: definition.verboseName || ""
            })
        )
      );
      this.addButton.addEventListener("click", function () {
        var row = self.addRow({}, true);

        if (row) {
          var first = row.element.querySelector("input, select, textarea");

          if (first) {
            first.focus();
          }
        }

        self.form.updateDirty();
      });
      footer.appendChild(this.addButton);
    } else {
      footer.appendChild(el("span"));
    }

    footer.appendChild(this.hint);

    root.append(header, this.errors, this.container, this.empty, footer);
    this.root = root;
  };

  /* -- Rows ------------------------------------------------------------- */

  Inline.prototype.clear = function () {
    this.rows.forEach(function (row) {
      Object.keys(row.widgets).forEach(function (name) {
        row.widgets[name].destroy();
      });
      row.element.remove();
    });

    this.rows = [];
    this.sentRows = [];
  };

  Inline.prototype.populate = function (rows) {
    var self = this;
    var definition = this.definition;

    this.clear();

    (rows || []).forEach(function (values) {
      self.addRow(values, false);
    });

    if (!this.readOnly && definition.canAdd) {
      for (var index = 0; index < (definition.extra || 0); index += 1) {
        this.addRow({}, true);
      }
    }

    this.update();
  };

  Inline.prototype.activeCount = function () {
    return this.rows.filter(function (row) {
      return !row.deleted;
    }).length;
  };

  Inline.prototype.addRow = function (values, isNew) {
    var self = this;
    var definition = this.definition;

    values = values || {};

    if (
      isNew &&
      definition.maxRows !== undefined &&
      definition.maxRows !== null &&
      this.activeCount() >= definition.maxRows
    ) {
      return null;
    }

    counter += 1;

    var editable = !this.readOnly && (isNew ? definition.canAdd : definition.canChange);
    var labels = values._display || {};
    var row = {
      key: "row" + counter,
      primaryKey: values[definition.primaryKey || "id"],
      isNew: isNew,
      deleted: false,
      widgets: {},
      cells: {},
      initial: null
    };

    if (row.primaryKey === undefined) {
      row.primaryKey = null;
    }

    var deleteButton = null;

    if (!this.readOnly && (isNew || definition.canDelete)) {
      deleteButton = el("button", "icon-button icon-button--sm");
      deleteButton.type = "button";
      deleteButton.addEventListener("click", function () {
        self.toggleDelete(row);
      });
      row.deleteButton = deleteButton;
    }

    if (this.tabular) {
      row.element = el("tr", "inline-row" + (isNew ? " is-new" : ""));

      this.fields().forEach(function (field) {
        var cell = el("td", "inline-cell");
        cell.dataset.label = field.label || field.name;

        var widget = forms.widgets.create(field, {
          readOnly: !editable || field.readOnly,
          compact: true,
          hideLabel: true
        });

        if (widget.focus && widget.focus.setAttribute) {
          widget.focus.setAttribute("aria-label", field.label || field.name);
        }

        var errors = el("ul", "inline-cell-errors");
        cell.append(self.form.wrapRelation(field, widget, !editable || field.readOnly), errors);
        row.element.appendChild(cell);
        row.widgets[field.name] = widget;
        row.cells[field.name] = { cell: cell, errors: errors };
      });

      var actions = el("td", "inline-table__actions");

      if (deleteButton) {
        actions.appendChild(deleteButton);
      }

      row.element.appendChild(actions);
    } else {
      row.element = el("div", "inline-card" + (isNew ? " is-new" : ""));

      var cardHeader = el("div", "inline-card__header");
      row.title = el("span", "", values._label || definition.verboseName || "");

      // A saved row is named after its record; a new one is numbered,
      // and renumbered as rows come and go.
      if (values._label) {
        row.title.dataset.fixed = "true";
      }
      cardHeader.appendChild(row.title);

      if (deleteButton) {
        cardHeader.appendChild(deleteButton);
      }

      var cardBody = el("div", "inline-card__body");
      var grid = el("div", "sf-grid");

      this.fields().forEach(function (field) {
        var box = el("div", "sf-field");
        box.style.setProperty("--field-width", String(field.width || 6));

        var readOnly = !editable || field.readOnly;
        var widget = forms.widgets.create(field, { readOnly: readOnly });
        var id = self.form.id + "-" + definition.name + "-" + row.key + "-" + field.name;

        if (widget.focus) {
          widget.focus.id = id;
        }

        var isSwitch = !readOnly && field.type === "boolean";

        if (!isSwitch) {
          var label = el("label", "sf-label", field.label || field.name);
          label.htmlFor = id;
          box.appendChild(label);
        }

        var errors = el("ul", "inline-cell-errors");
        box.append(self.form.wrapRelation(field, widget, readOnly), errors);
        grid.appendChild(box);
        row.widgets[field.name] = widget;
        row.cells[field.name] = { cell: box, errors: errors };
      });

      cardBody.appendChild(grid);
      row.element.append(cardHeader, cardBody);
    }

    this.body.appendChild(row.element);

    this.fields().forEach(function (field) {
      var widget = row.widgets[field.name];

      if (self.root.isConnected) {
        widget.mount();
      }

      var value = values[field.name];

      if (value === undefined) {
        value = field.default !== undefined ? field.default : null;
      }

      widget.set(value, labels[field.name]);
    });

    row.initial = this.rowValues(row);
    this.rows.push(row);
    this.renderDeleteButton(row);
    this.update();

    return row;
  };

  Inline.prototype.renderDeleteButton = function (row) {
    var button = row.deleteButton;

    if (!button) {
      return;
    }

    var undo = row.deleted;
    var label = undo ? t("Undo") : this.definition.deleteLabel || t("Remove");

    button.replaceChildren(icon(undo ? "undo" : "delete", "icon--sm"));
    button.title = label;
    button.setAttribute("aria-label", label);
  };

  Inline.prototype.toggleDelete = function (row) {
    // A row that was never saved simply goes away.
    if (row.isNew) {
      Object.keys(row.widgets).forEach(function (name) {
        row.widgets[name].destroy();
      });
      row.element.remove();
      this.rows = this.rows.filter(function (candidate) {
        return candidate !== row;
      });
    } else {
      row.deleted = !row.deleted;
      row.element.classList.toggle("is-deleted", row.deleted);

      var editable = !this.readOnly && this.definition.canChange;

      Object.keys(row.widgets).forEach(function (name) {
        row.widgets[name].disable(row.deleted || !editable);
      });

      this.renderDeleteButton(row);
    }

    this.update();
    this.form.updateDirty();
  };

  /* -- Values ------------------------------------------------------------- */

  Inline.prototype.rowValues = function (row) {
    var self = this;
    var values = {};
    var key = this.definition.primaryKey || "id";

    if (row.primaryKey !== null) {
      values[key] = row.primaryKey;
    }

    this.fields().forEach(function (field) {
      var widget = row.widgets[field.name];

      if (!widget || widget.readOnly || field.readOnly) {
        return;
      }

      var value = self.form.normalize(field, widget.get());

      if (value !== undefined) {
        values[field.name] = value;
      }
    });

    if (row.deleted) {
      values._delete = true;
    }

    return values;
  };

  /** A new row nobody typed into: not worth sending. */
  Inline.prototype.isBlank = function (row, values) {
    if (!row.isNew || row.deleted) {
      return false;
    }

    var key = this.definition.primaryKey || "id";

    return this.fields().every(function (field) {
      if (field.name === key || !(field.name in values)) {
        return true;
      }

      var value = values[field.name];

      if (forms.widgets.isEmpty(value) || value === false) {
        return true;
      }

      return field.default !== undefined && same(value, field.default);
    });
  };

  /**
   * The rows to send, and which row each position stands for.
   *
   * `changedOnly` leaves out existing rows nobody touched.
   */
  Inline.prototype.collect = function (changedOnly) {
    var self = this;
    var payload = [];

    this.sentRows = [];

    this.rows.forEach(function (row) {
      var values = self.rowValues(row);

      if (self.isBlank(row, values)) {
        return;
      }

      if (changedOnly && !row.isNew && !row.deleted && same(values, row.initial)) {
        return;
      }

      payload.push(values);
      self.sentRows.push(row);
    });

    return payload;
  };

  Inline.prototype.isDirty = function () {
    var self = this;

    return this.rows.some(function (row) {
      if (row.deleted) {
        return true;
      }

      var values = self.rowValues(row);

      if (row.isNew) {
        return !self.isBlank(row, values);
      }

      return !same(values, row.initial);
    });
  };

  /* -- Errors -------------------------------------------------------------- */

  Inline.prototype.clearErrors = function () {
    this.errors.replaceChildren();
    this.root.classList.remove("has-error");

    this.rows.forEach(function (row) {
      Object.keys(row.cells).forEach(function (name) {
        row.cells[name].cell.classList.remove("has-error");
        row.cells[name].errors.replaceChildren();
      });
    });
  };

  Inline.prototype.addCollectionError = function (message) {
    this.errors.appendChild(el("div", "", message));
    this.root.classList.add("has-error");
  };

  /** Show the server's errors. Returns how many there were. */
  Inline.prototype.showErrors = function (errors) {
    var self = this;
    var count = 0;

    Object.keys(errors || {}).forEach(function (position) {
      var value = errors[position];

      if (position === "_errors") {
        messagesOf(value).forEach(function (message) {
          self.addCollectionError(message);
          count += 1;
        });
        return;
      }

      var row = self.sentRows[Number(position)];

      if (!row) {
        messagesOf(value).forEach(function (message) {
          self.addCollectionError(message);
          count += 1;
        });
        return;
      }

      var number = self.rows.indexOf(row) + 1;

      Object.keys(value || {}).forEach(function (name) {
        var entry = row.cells[name];

        messagesOf(value[name]).forEach(function (message) {
          if (entry) {
            entry.cell.classList.add("has-error");
            entry.errors.appendChild(el("li", "", message));
          } else {
            self.addCollectionError(
              Generic.format(t("Row %(number)s: %(message)s"), {
                number: number,
                message: message
              })
            );
          }

          count += 1;
        });
      });
    });

    if (count) {
      this.root.classList.add("has-error");
    }

    return count;
  };

  /* -- State --------------------------------------------------------------- */

  Inline.prototype.update = function () {
    var definition = this.definition;
    var active = this.activeCount();

    this.count.textContent = String(active);
    this.empty.hidden = this.rows.length > 0;

    if (this.tabular) {
      this.container.hidden = this.rows.length === 0;
    }

    var maximum = definition.maxRows;
    var full = maximum !== undefined && maximum !== null && active >= maximum;

    if (this.addButton) {
      this.addButton.disabled = full;
    }

    if (maximum !== undefined && maximum !== null) {
      this.hint.textContent = Generic.format(t("%(count)s of %(maximum)s at most"), {
        count: active,
        maximum: maximum
      });
    } else {
      this.hint.textContent = "";
    }

    if (!this.tabular) {
      var index = 0;

      this.rows.forEach(function (row) {
        index += 1;

        if (row.title && !row.title.dataset.fixed) {
          row.title.textContent =
            (definition.verboseName || "") + " #" + index;
        }
      });
    }
  };

  Inline.prototype.mountAll = function () {
    this.rows.forEach(function (row) {
      Object.keys(row.widgets).forEach(function (name) {
        row.widgets[name].mount();
      });
    });
  };

  Inline.prototype.destroy = function () {
    this.clear();
  };

  forms.Inline = Inline;
  forms.messagesOf = messagesOf;
})(window, document);

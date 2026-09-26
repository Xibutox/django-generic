/**
 * A table built for correcting many rows while seeing the whole set.
 *
 * Every cell that may be written is its control from the start - an
 * input, a select, a checkbox, an autocomplete - and nothing in the
 * table leads anywhere else: the server has already taken the links and
 * the row menu away (generic.sites.editable.as_grid). What is left is
 * the work.
 *
 * The controls are the form renderer's own, built from the same field
 * schema the form reads, so nothing here knows what a field means.
 *
 * A cell is written when it changes: at once for anything picked from
 * a list or ticked, when the reader leaves it or presses Enter for
 * anything typed. One request per cell. The answer is the whole row,
 * which updates the cells around it without rebuilding the controls -
 * rebuilding would take the focus from under the reader's fingers.
 *
 * "Add a row" puts a draft at the top: the controls of the columns a
 * new record writes, sent together when the reader saves it (see "New
 * rows" below).
 */
(function (window, document) {
  "use strict";

  var namespace = window.GenericDataTables;
  var core = namespace.core;
  var t = core.t;
  var el = core.el;

  function widgets() {
    var Generic = window.Generic;

    return Generic.forms && Generic.forms.widgets;
  }

  function described(controller) {
    return controller.options.editable || {};
  }

  /** The columns this reader may write, with their index. */
  function editableColumns(controller) {
    var schemas = described(controller);

    return controller.columns
      .map(function (column, index) {
        return { column: column, index: index };
      })
      .filter(function (entry) {
        return Boolean(entry.column.data && schemas[entry.column.data]);
      });
  }

  /**
   * The value a control opens on. A row carries raw values - the key of
   * a choice, the id of a relation beside its label - which is exactly
   * what the control wants back.
   */
  function valueOf(row, name, schema) {
    if (schema.relation) {
      var key = "_fk_" + name;

      if (Object.prototype.hasOwnProperty.call(row, key)) {
        return row[key];
      }
    }

    var value = row[name];

    // A column drawn as tags: each tag carries what it stands for - a
    // choice its value, a record its id - beside the label shown.
    if (isTags(value)) {
      var keys = value.map(tagKey);

      return schema.type === "multiselect" ? keys : keys.length ? keys[0] : null;
    }

    return value === undefined ? null : value;
  }

  function isTags(value) {
    return (
      Array.isArray(value) &&
      value.every(function (item) {
        return item && typeof item === "object" && "label" in item;
      })
    );
  }

  function tagKey(tag) {
    return tag.value !== undefined ? tag.value : tag.id;
  }

  function labelsOf(row, name, schema, value) {
    var labels = {};
    var shown = row[name];

    if (!schema.relation || value === null || value === undefined) {
      return labels;
    }

    if (isTags(shown)) {
      shown.forEach(function (tag) {
        labels[String(tagKey(tag))] = String(tag.label);
      });

      return labels;
    }

    labels[String(value)] = shown === null ? "" : String(shown);

    return labels;
  }

  function sameValue(before, after) {
    if (Array.isArray(before) || Array.isArray(after)) {
      return JSON.stringify(before || []) === JSON.stringify(after || []);
    }

    if (before === null || before === undefined || before === "") {
      return after === null || after === undefined || after === "";
    }

    return String(before) === String(after);
  }

  function focusWithin(node) {
    return Boolean(node && node.contains(document.activeElement));
  }

  //: How long a change this page made itself is recognised when the
  //: socket reports it back.
  var OWN_WRITE_MS = 5000;

  /**
   * Whether the grid is in use: a control has the focus, a Select2
   * list is open (it lives outside the table), or a cell is on its way
   * to the server. A redraw now would take the reader's work with it.
   */
  function busy(controller) {
    return Boolean(
      focusWithin(controller.table) ||
        document.querySelector(".select2-container--open") ||
        controller.grid.some(function (cell) {
          return cell.saving || cell.pending;
        }) ||
        (controller.drafts || []).some(function (draft) {
          return draft.saving;
        })
    );
  }

  function rowKey(controller, row) {
    var key = controller.options.rowKey || "_pk";

    return row && row[key] !== undefined ? String(row[key]) : "";
  }

  /** Once the reader has put the grid down, a waiting reload may run. */
  function releaseWhenIdle(controller) {
    window.setTimeout(function () {
      if (!busy(controller) && controller.releaseReload) {
        controller.releaseReload();
      }
    }, 0);
  }

  /**
   * A column of another record, written on one row, is the same value
   * on every row pointing at that record - the ticket's status on each
   * of the ticket's entries. They follow at once; where the rows do not
   * say which record they point at, the table reloads when it may.
   */
  function propagate(cell, row) {
    var controller = cell.controller;
    var parts = cell.name.split("__");

    if (parts.length < 2) {
      return;
    }

    var link = "_fk_" + parts[0];

    if (!Object.prototype.hasOwnProperty.call(row, link)) {
      if (controller.requestReload) {
        controller.requestReload();
      }

      return;
    }

    var api = controller.instance;
    var value = valueOf(row, cell.name, cell.schema);

    controller.grid.forEach(function (other) {
      if (other === cell || other.name !== cell.name || other.gone) {
        return;
      }

      var theirs = api.row(other.rowIndex).data();

      if (!theirs || String(theirs[link]) !== String(row[link])) {
        return;
      }

      theirs[cell.name] = row[cell.name];

      if (Object.prototype.hasOwnProperty.call(row, "_fk_" + cell.name)) {
        theirs["_fk_" + cell.name] = row["_fk_" + cell.name];
      }

      other.saved = value;

      if (!focusWithin(other.td)) {
        other.widget.set(value, labelsOf(row, cell.name, cell.schema, value));
      }
    });
  }

  /* -- One cell ------------------------------------------------------- */

  function clearError(cell) {
    cell.td.classList.remove("is-invalid");

    if (cell.error) {
      cell.error.remove();
      cell.error = null;
    }
  }

  function showError(cell, error) {
    var detail = error && error.data;
    var messages = detail && detail[cell.name];
    var message = Array.isArray(messages)
      ? messages.join(" ")
      : messages ||
        (detail && detail.detail) ||
        (error && error.message) ||
        t("This could not be saved.");

    cell.td.classList.add("is-invalid");

    if (!cell.error) {
      cell.error = el("div", "cell-editor__error");
      cell.td.appendChild(cell.error);
    }

    cell.error.textContent = message;
  }

  /** Mark a saved cell for a moment, so the eye can follow the work. */
  function flash(td) {
    td.classList.remove("is-saved");
    // Restart the animation even when the same cell saves twice.
    void td.offsetWidth;
    td.classList.add("is-saved");
    window.setTimeout(function () {
      td.classList.remove("is-saved");
    }, 1200);
  }

  /**
   * Bring the rest of the row up to date from the server's answer.
   *
   * Read-only cells are drawn again from the row's data; the other
   * controls take their new value only if the reader is not in them.
   * The cell that was just written is left as the reader left it.
   */
  function refreshRow(controller, rowIndex, written) {
    var api = controller.instance;
    var writable = {};

    controller.grid.forEach(function (cell) {
      if (cell.rowIndex !== rowIndex) {
        return;
      }

      writable[cell.columnIndex] = true;

      if (cell === written || focusWithin(cell.td)) {
        return;
      }

      var row = api.row(rowIndex).data();
      var value = valueOf(row, cell.name, cell.schema);

      if (!sameValue(cell.saved, value)) {
        cell.saved = value;
        cell.widget.set(value, labelsOf(row, cell.name, cell.schema, value));
      }
    });

    controller.dataColumns().forEach(function (entry) {
      if (!writable[entry.index]) {
        api.cell(rowIndex, entry.index).invalidate();
      }
    });
  }

  function commit(cell) {
    var controller = cell.controller;
    var Generic = window.Generic;
    var value = cell.widget.get();

    if (sameValue(cell.saved, value)) {
      clearError(cell);

      return;
    }

    // A second change while the first is on its way is sent after it,
    // so the last thing typed is the last thing written.
    if (cell.saving) {
      cell.pending = true;

      return;
    }

    var api = controller.instance;
    var row = api.row(cell.rowIndex).data();
    var url = core.fillTemplate(controller.options.editableUrl, row);

    if (!url) {
      return;
    }

    var body = {};
    body[cell.name] = value;

    cell.saving = true;
    cell.td.classList.add("is-saving");
    // Before the request: the socket may announce the change before the
    // answer arrives, and the grid already knows about it.
    controller.recentWrites[rowKey(controller, row)] = Date.now();

    Generic.api
      .patch(url, body)
      .then(function (fresh) {
        // The table has moved to another page meanwhile: the row is
        // saved, and there is nothing left on screen to update.
        if (cell.gone) {
          return;
        }

        // In place, not through row().data(): DataTables would draw
        // the row again and every control in it would be rebuilt.
        Object.assign(row, fresh);

        var saved = valueOf(row, cell.name, cell.schema);

        // The server may write the value differently - "2" becomes
        // "2.00" - and says so; the control shows it unless the reader
        // has typed something else meanwhile.
        if (sameValue(cell.widget.get(), value)) {
          cell.widget.set(saved, labelsOf(row, cell.name, cell.schema, saved));
        }

        cell.saved = saved;
        clearError(cell);
        refreshRow(controller, cell.rowIndex, cell);
        propagate(cell, row);
        flash(cell.td);
      })
      .catch(function (error) {
        if (!cell.gone) {
          showError(cell, error);
        }
      })
      .then(function () {
        cell.saving = false;
        cell.td.classList.remove("is-saving");

        if (cell.pending && !cell.gone) {
          cell.pending = false;
          commit(cell);

          return;
        }

        releaseWhenIdle(controller);
      });
  }

  /** Enter in a typed cell goes down a row, as it does in a sheet. */
  function moveDown(cell) {
    var controller = cell.controller;
    var order = controller.instance.rows({ page: "current" }).indexes().toArray();
    var next = order[order.indexOf(cell.rowIndex) + 1];

    if (next === undefined) {
      return;
    }

    var node = controller.instance.cell(next, cell.columnIndex).node();
    var target = node && node.gridCell;

    if (target && target.widget.focus && target.widget.focus.focus) {
      target.widget.focus.focus();

      if (target.widget.focus.select) {
        target.widget.focus.select();
      }
    }
  }

  function bind(cell) {
    var td = cell.td;

    function changed() {
      commit(cell);
    }

    // A native control says "change"; a Select2 control says
    // "generic:change", because jQuery's own event never reaches a
    // listener added here.
    td.addEventListener("change", changed);
    td.addEventListener("generic:change", changed);

    // And leaving the cell writes it too: a value filled in by the
    // browser's autocomplete, or by a script, never says "change".
    // Nothing is sent when nothing differs from what is saved.
    td.addEventListener("focusout", function () {
      window.setTimeout(function () {
        if (!cell.gone && !focusWithin(td)) {
          commit(cell);
        }
      }, 0);
    });

    td.addEventListener("keydown", function (event) {
      var target = event.target;
      var typed =
        target.tagName === "INPUT" &&
        target.type !== "checkbox" &&
        target.type !== "radio";

      if (event.key === "Enter" && typed) {
        event.preventDefault();
        commit(cell);
        moveDown(cell);
      } else if (event.key === "Escape") {
        // Back to what is saved, before it is sent anywhere.
        var row = cell.controller.instance.row(cell.rowIndex).data();

        cell.widget.set(
          cell.saved,
          labelsOf(row, cell.name, cell.schema, cell.saved)
        );
        clearError(cell);
      }
    });
  }

  function mountCell(controller, td, rowIndex, columnIndex, name, schema) {
    var row = controller.instance.row(rowIndex).data();
    var widget = widgets().create(schema, { compact: true });
    var value = valueOf(row, name, schema);
    var holder = el("div", "cell-editor");

    var cell = {
      controller: controller,
      td: td,
      rowIndex: rowIndex,
      columnIndex: columnIndex,
      name: name,
      schema: schema,
      widget: widget,
      saved: value,
      saving: false,
      pending: false,
      error: null
    };

    td.textContent = "";
    td.classList.add("grid-cell");
    holder.appendChild(widget.root);
    td.appendChild(holder);

    if (widget.focus && schema.label) {
      widget.focus.setAttribute("aria-label", schema.label);
    }

    if (widget.mount) {
      widget.mount();
    }

    widget.set(value, labelsOf(row, name, schema, value));

    td.gridCell = cell;
    controller.grid.push(cell);
    bind(cell);
  }

  /* -- The whole grid ------------------------------------------------- */

  /** A control in every writable cell of the rows in view. */
  function mountAll(controller) {
    var api = controller.instance;
    var schemas = described(controller);
    var columns = editableColumns(controller).filter(function (entry) {
      // Only what is shown: a control built in a hidden column would
      // measure itself against nothing. Showing the column mounts it.
      return api.column(entry.index).visible();
    });

    api.rows({ page: "current" }).indexes().each(function (rowIndex) {
      columns.forEach(function (entry) {
        var td = api.cell(rowIndex, entry.index).node();

        if (!td || td.gridCell) {
          return;
        }

        mountCell(
          controller,
          td,
          rowIndex,
          entry.index,
          entry.column.data,
          schemas[entry.column.data]
        );
      });
    });
  }

  /** Before the rows go, their controls go: Select2 lives outside them. */
  function destroyAll(controller) {
    controller.grid.forEach(function (cell) {
      // A save still on its way lands in the database; it must not
      // land on whatever row now holds this index.
      cell.gone = true;

      if (cell.widget.destroy) {
        cell.widget.destroy();
      }

      cell.td.gridCell = null;
    });

    controller.grid = [];
  }

  /* -- New rows ------------------------------------------------------
   *
   * A draft is not one of the table's rows: DataTables draws what the
   * server sends, and would drop it at the next page. The grid keeps
   * its drafts and puts them back on top after every draw - DataTables
   * detaches the rows it replaces, so the controls survive the move.
   *
   * A draft is sent whole, when the reader saves it: a record that does
   * not exist yet cannot be written one cell at a time. Which columns
   * it writes, where they start and what the new record gets without
   * asking - the ticket it belongs to - are the server's (gridAdd).
   */

  function adding(controller) {
    return controller.options.gridAdd || null;
  }

  function shownColumns(controller) {
    var api = controller.instance;

    return controller.columns
      .map(function (column, index) {
        return { column: column, index: index };
      })
      .filter(function (entry) {
        return api.column(entry.index).visible();
      });
  }

  function smallButton(iconName, label, extra) {
    var button = el("button", "icon-button icon-button--sm " + (extra || ""));

    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(core.icon(iconName, "icon--sm"));

    return button;
  }

  function draftValues(draft) {
    var values = {};

    Object.keys(draft.cells).forEach(function (name) {
      values[name] = draft.cells[name].widget.get();
    });

    return values;
  }

  function isEmpty(value) {
    return (
      value === null ||
      value === undefined ||
      value === "" ||
      (Array.isArray(value) && !value.length)
    );
  }

  /**
   * What is sent: what the reader filled in. An empty control is left
   * out rather than sent as nothing, so the model's own default applies
   * and a required field says it is required, not that it cannot be
   * null.
   */
  function filledValues(draft) {
    var values = draftValues(draft);

    Object.keys(values).forEach(function (name) {
      if (isEmpty(values[name])) {
        delete values[name];
      }
    });

    return values;
  }

  function clearDraftErrors(draft) {
    Object.keys(draft.cells).forEach(function (name) {
      clearError(draft.cells[name]);
    });

    draft.message.hidden = true;
    draft.messageCell.textContent = "";
  }

  /**
   * Each message under the cell it is about; the rest - a required
   * field the grid does not show, a rule about the whole record - on a
   * line of its own under the row.
   */
  function showDraftErrors(draft, error) {
    var detail = error && error.data;
    var rest = [];

    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      Object.keys(detail).forEach(function (key) {
        var messages = [].concat(detail[key]).join(" ");

        if (draft.cells[key]) {
          showError(draft.cells[key], { data: detail });
        } else {
          rest.push(messages);
        }
      });
    } else {
      rest.push((error && error.message) || t("This row could not be added."));
    }

    if (rest.length) {
      draft.messageCell.textContent = rest.join(" ");
      draft.message.hidden = false;
    }
  }

  function removeDraft(draft) {
    var controller = draft.controller;

    Object.keys(draft.cells).forEach(function (name) {
      var widget = draft.cells[name].widget;

      if (widget.destroy) {
        widget.destroy();
      }
    });

    draft.tr.remove();
    draft.message.remove();
    controller.drafts = controller.drafts.filter(function (other) {
      return other !== draft;
    });
    releaseWhenIdle(controller);
  }

  function saveDraft(draft) {
    var controller = draft.controller;
    var add = adding(controller);

    if (draft.saving || !add) {
      return;
    }

    clearDraftErrors(draft);
    draft.saving = true;
    draft.tr.classList.add("is-saving");

    window.Generic.api
      .post(add.url, filledValues(draft))
      .then(function (row) {
        var key = rowKey(controller, row || {});

        removeDraft(draft);

        if (key) {
          // The socket will announce it: the grid knows already.
          controller.recentWrites[key] = Date.now();
          controller.justAdded = key;
        }

        window.Generic.toast(t("The row was added."), "success");
        controller.reload(false);
      })
      .catch(function (error) {
        showDraftErrors(draft, error);
      })
      .then(function () {
        draft.saving = false;
        draft.tr.classList.remove("is-saving");
      });
  }

  /** The draft's cells, one per column shown, in the table's order. */
  function buildDraft(controller) {
    var add = adding(controller);
    var tr = el("tr", "grid-draft");
    var message = el("tr", "grid-draft__message");
    var messageCell = el("td");
    var actions = el("div", "grid-draft__actions");
    var draft = {
      controller: controller,
      tr: tr,
      message: message,
      messageCell: messageCell,
      cells: {},
      saving: false
    };
    var save = smallButton("check", t("Add this row"), "grid-draft__save");
    var cancel = smallButton("close", t("Discard this row"));
    var columns = shownColumns(controller);
    var holder = null;

    save.addEventListener("click", function () {
      saveDraft(draft);
    });
    cancel.addEventListener("click", function () {
      removeDraft(draft);
    });
    actions.append(save, cancel);

    columns.forEach(function (entry) {
      var name = entry.column.data;
      var schema = name ? add.columns[name] : null;
      var td = el("td");

      if (entry.column.synthetic) {
        td.className = "dt-select";
      } else if (schema) {
        var widget = widgets().create(schema, { compact: true });
        var editor = el("div", "cell-editor");

        editor.appendChild(widget.root);
        td.className = "grid-cell";
        td.appendChild(editor);

        if (widget.focus && schema.label) {
          widget.focus.setAttribute("aria-label", schema.label);
        }

        draft.cells[name] = { td: td, name: name, schema: schema, widget: widget };
      }

      // The buttons go first: in the selection column when there is
      // one, before the first cell otherwise.
      if (!holder && (entry.column.synthetic || !columns[0].column.synthetic)) {
        var control = td.querySelector(".cell-editor");

        holder = td;

        if (control) {
          var lead = el("div", "grid-draft__lead");

          td.insertBefore(lead, control);
          lead.append(actions, control);
        } else {
          td.insertBefore(actions, td.firstChild);
        }
      }

      tr.appendChild(td);
    });

    messageCell.colSpan = Math.max(1, columns.length);
    messageCell.className = "grid-draft__message-cell";
    message.appendChild(messageCell);
    message.hidden = true;

    // Enter in a typed control adds the row, as it writes a cell.
    tr.addEventListener("keydown", function (event) {
      var target = event.target;

      if (
        event.key === "Enter" &&
        target.tagName === "INPUT" &&
        target.type !== "checkbox" &&
        target.type !== "radio"
      ) {
        event.preventDefault();
        saveDraft(draft);
      }
    });

    return draft;
  }

  /** Controls are started once in the page: Select2 measures itself. */
  function startDraft(draft, values) {
    var add = adding(draft.controller);
    var labels = add.labels || {};

    Object.keys(draft.cells).forEach(function (name) {
      var cell = draft.cells[name];
      var value = Object.prototype.hasOwnProperty.call(values, name)
        ? values[name]
        : null;

      if (cell.widget.mount) {
        cell.widget.mount();
      }

      cell.widget.set(value, labels[name] || {});
    });
  }

  /** Back on top of the rows, newest first, after every draw. */
  function placeDrafts(controller) {
    var body = controller.table.tBodies[0];

    if (!body) {
      return;
    }

    for (var index = controller.drafts.length - 1; index >= 0; index -= 1) {
      var draft = controller.drafts[index];

      body.insertBefore(draft.message, body.firstChild);
      body.insertBefore(draft.tr, body.firstChild);
    }
  }

  function addDraft(controller) {
    var add = adding(controller);
    var draft = buildDraft(controller);
    var first = null;

    controller.drafts.unshift(draft);
    placeDrafts(controller);
    startDraft(draft, add.initial || {});

    Object.keys(draft.cells).some(function (name) {
      first = draft.cells[name].widget.focus;

      return Boolean(first);
    });

    if (first && first.focus) {
      first.focus();
    }
  }

  /** Shown or hidden columns: the drafts are drawn again, as typed. */
  function redrawDrafts(controller) {
    var typed = controller.drafts.map(draftValues);
    var old = controller.drafts;

    controller.drafts = [];
    old.forEach(function (draft) {
      Object.keys(draft.cells).forEach(function (name) {
        if (draft.cells[name].widget.destroy) {
          draft.cells[name].widget.destroy();
        }
      });
      draft.tr.remove();
      draft.message.remove();
    });

    controller.drafts = old.map(function () {
      return buildDraft(controller);
    });
    placeDrafts(controller);
    controller.drafts.forEach(function (draft, index) {
      startDraft(draft, typed[index]);
    });
  }

  /** The row just added, marked when it is on the page. */
  function markAdded(controller) {
    var key = controller.justAdded;
    var api = controller.instance;

    if (!key) {
      return;
    }

    controller.justAdded = null;
    api.rows({ page: "current" }).every(function () {
      if (rowKey(controller, this.data()) === key) {
        Array.prototype.forEach.call(this.node().cells, flash);
      }
    });
  }

  function buildAddButton(controller) {
    var button = el("button", "button button--sm dt-tool dt-tool--add");

    button.type = "button";
    button.title = t("Add a row");
    button.append(
      core.icon("add", "icon--sm"),
      el("span", "dt-tool__label", t("Add a row"))
    );
    button.addEventListener("click", function () {
      addDraft(controller);
    });

    return button;
  }

  core.registerFeature({
    name: "editable",

    enabled: function (controller) {
      var writes = Boolean(
        controller.options.editableUrl &&
          Object.keys(described(controller)).length
      );
      var add = adding(controller);

      // A reader who may add rows but change none still gets the grid.
      return Boolean(
        widgets() && (writes || (add && Object.keys(add.columns || {}).length))
      );
    },

    init: function (controller) {
      var api = controller.instance;

      controller.grid = [];
      controller.drafts = [];
      controller.recentWrites = {};
      controller.table.classList.add("is-grid");

      if (adding(controller) && controller.slots.tools) {
        controller.slots.tools.insertBefore(
          buildAddButton(controller),
          controller.slots.tools.firstChild
        );
      }

      // The live refresh asks before it redraws (realtime.js).
      controller.holdsReload = function () {
        return busy(controller);
      };

      controller.skipsChange = function (payload) {
        var key = payload && payload.id !== null && payload.id !== undefined
          ? String(payload.id)
          : "";
        var at = controller.recentWrites[key];

        return Boolean(at && Date.now() - at < OWN_WRITE_MS);
      };

      controller.table.addEventListener("focusout", function () {
        releaseWhenIdle(controller);
      });

      api.on("preDraw.dt.editable", function () {
        destroyAll(controller);
      });
      api.on("draw.dt.editable", function () {
        mountAll(controller);
        placeDrafts(controller);
        markAdded(controller);
      });
      api.on("column-visibility.dt.editable", function () {
        mountAll(controller);
        redrawDrafts(controller);
      });

      mountAll(controller);
    },

    destroy: function (controller) {
      destroyAll(controller);
      (controller.drafts || []).slice().forEach(removeDraft);
      controller.instance.off(".editable");
    }
  });
})(window, document);

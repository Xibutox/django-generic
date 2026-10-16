/**
 * Bulk edit: the selected rows given one value per chosen field.
 *
 * Opened from a table's selection bar (selection.js). The reader adds
 * the fields to change, one line each - the field, what to do to it
 * (set, clear, or add to / remove from a many-to-many), the value, in
 * the control the form itself would use - then reviews: the server
 * runs the whole edit and rolls it back, answering how many records
 * would change and which would be left as they are, and why. Only
 * then does the button write. Changing anything asks for a new review.
 *
 *   Generic.bulkEdit.open({url, body, count, title})
 *     .then(function (answer) { ... });   // null when cancelled
 *
 * `body` is the selection as the actions endpoint takes it ({ids} or
 * {all: true}, the table's filters then in `url`).
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

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

  function icon(name) {
    var node = el("span", "icon material-symbols-outlined icon--sm", name);
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  function button(label, className, iconName) {
    var node = el("button", "button " + (className || ""));
    node.type = "button";

    if (iconName) {
      node.appendChild(icon(iconName));
    }

    node.appendChild(el("span", "", label));

    return node;
  }

  function widgets() {
    return Generic.forms && Generic.forms.widgets;
  }

  /** One line of the dialog: a field, what to do to it, its value. */
  function Line(editor) {
    var line = this;

    this.editor = editor;
    this.field = null;
    this.widget = null;
    this.root = el("div", "bulk-edit__line");
    this.choose = el("select", "input input--sm bulk-edit__field");
    this.mode = el("select", "input input--sm bulk-edit__mode");
    this.value = el("div", "bulk-edit__value");
    this.remove = el("button", "icon-button icon-button--sm bulk-edit__remove");

    this.choose.setAttribute("aria-label", t("Field"));
    this.mode.setAttribute("aria-label", t("What to do"));
    this.remove.type = "button";
    this.remove.setAttribute("aria-label", t("Remove this line"));
    this.remove.title = t("Remove this line");
    this.remove.appendChild(icon("close"));

    this.root.append(this.choose, this.mode, this.value, this.remove);

    this.choose.addEventListener("change", function () {
      line.pick(line.choose.value);
      editor.refreshChoices();
    });

    this.mode.addEventListener("change", function () {
      line.showValue();
    });

    this.remove.addEventListener("click", function () {
      editor.removeLine(line);
    });
  }

  Line.prototype.fillChoices = function (taken) {
    var line = this;
    var current = this.field ? this.field.name : "";

    this.choose.textContent = "";
    this.choose.appendChild(new Option(t("Choose a field") + "\u2026", ""));

    this.editor.fields.forEach(function (field) {
      if (field.name !== current && taken[field.name]) {
        return;
      }

      var option = new Option(field.label, field.name);
      option.selected = field.name === current;
      line.choose.appendChild(option);
    });
  };

  Line.prototype.pick = function (name) {
    var field = this.editor.byName[name] || null;
    var mode = this.mode;

    this.dropWidget();
    this.field = field;
    mode.textContent = "";

    if (!field) {
      mode.hidden = true;
      this.value.hidden = true;
      return;
    }

    (field.modes || []).forEach(function (entry) {
      mode.appendChild(new Option(entry.label, entry.value));
    });

    // One thing to do - set it - needs no question.
    mode.hidden = (field.modes || []).length < 2;

    var widget = widgets().create(field, {
      compact: true,
      dropdownParent: this.editor.dialog.dialog
    });

    this.widget = widget;
    this.value.appendChild(widget.root);

    if (widget.focus) {
      widget.focus.setAttribute("aria-label", field.label);
    }

    if (widget.mount) {
      widget.mount();
    }

    if (field.type === "boolean" && widget.set) {
      widget.set(false);
    }

    this.showValue();

    if (widget.focus && widget.focus.focus) {
      widget.focus.focus();
    }
  };

  Line.prototype.showValue = function () {
    this.value.hidden = !this.field || this.mode.value === "clear";
  };

  Line.prototype.dropWidget = function () {
    if (this.widget && this.widget.destroy) {
      this.widget.destroy();
    }

    this.widget = null;
    this.value.textContent = "";
  };

  /** `{mode, value}`, or null for a line with no field yet. */
  Line.prototype.change = function () {
    if (!this.field) {
      return null;
    }

    var mode = this.mode.value || "set";

    if (mode === "clear") {
      return { mode: mode };
    }

    return { mode: mode, value: this.widget ? this.widget.get() : null };
  };

  /** The whole dialog. */
  function Editor(options, schema, dialog) {
    var editor = this;

    this.options = options;
    this.schema = schema;
    this.fields = schema.fields || [];
    this.byName = {};
    this.lines = [];
    this.dialog = dialog;
    this.reviewed = null;
    this.busy = false;

    this.fields.forEach(function (field) {
      editor.byName[field.name] = field;
    });

    this.linesNode = el("div", "bulk-edit__lines");
    this.add = button(t("Add a field"), "button--ghost button--sm", "add");
    this.review = el("div", "bulk-edit__review");
    this.review.setAttribute("aria-live", "polite");

    this.cancel = button(t("Cancel"), "button--ghost");
    this.primary = button("", "button--primary");

    dialog.body.append(
      el(
        "p",
        "muted bulk-edit__intro",
        Generic.format(
          t(
            "%(count)s %(name)s selected. Choose the fields to change and their new value: everything else is kept. Nothing is written before you have reviewed the change."
          ),
          {
            count: options.count,
            name: options.count === 1 ? schema.name : schema.namePlural
          }
        )
      ),
      this.linesNode,
      this.add,
      this.review
    );
    dialog.footer.append(this.cancel, this.primary);

    this.add.addEventListener("click", function () {
      editor.addLine();
    });

    this.cancel.addEventListener("click", function () {
      dialog.close(null);
    });

    this.primary.addEventListener("click", function () {
      if (editor.reviewed) {
        editor.send(true);
      } else {
        editor.send(false);
      }
    });

    // Whatever the reader changes, the review no longer describes it.
    ["change", "input", "generic:change"].forEach(function (type) {
      editor.linesNode.addEventListener(type, function () {
        editor.forget();
      });
    });

    this.addLine();
    this.forget();
  }

  Editor.prototype.taken = function () {
    var taken = {};

    this.lines.forEach(function (line) {
      if (line.field) {
        taken[line.field.name] = true;
      }
    });

    return taken;
  };

  Editor.prototype.refreshChoices = function () {
    var taken = this.taken();

    this.lines.forEach(function (line) {
      line.fillChoices(taken);
    });

    this.add.hidden = this.lines.length >= this.fields.length;
  };

  Editor.prototype.addLine = function () {
    var line = new Line(this);

    this.lines.push(line);
    this.linesNode.appendChild(line.root);
    line.mode.hidden = true;
    line.value.hidden = true;
    this.refreshChoices();
    this.forget();
    line.choose.focus();
  };

  Editor.prototype.removeLine = function (line) {
    line.dropWidget();
    line.root.remove();
    this.lines = this.lines.filter(function (other) {
      return other !== line;
    });

    if (!this.lines.length) {
      this.addLine();
      return;
    }

    this.refreshChoices();
    this.forget();
  };

  Editor.prototype.changes = function () {
    var changes = {};
    var count = 0;

    this.lines.forEach(function (line) {
      var change = line.change();

      if (change) {
        changes[line.field.name] = change;
        count += 1;
      }
    });

    return count ? changes : null;
  };

  /** Back to "review": what was reviewed is not what is asked now. */
  Editor.prototype.forget = function () {
    this.reviewed = null;
    this.review.textContent = "";
    this.primary.lastChild.textContent = t("Review the change");
    this.primary.disabled = this.busy;
  };

  Editor.prototype.send = function (commit) {
    var editor = this;
    var changes = this.changes();

    if (!changes) {
      this.showError(t("Choose at least one field to change."));
      return;
    }

    var body = Object.assign({}, this.options.body, {
      changes: changes,
      commit: Boolean(commit)
    });

    this.busy = true;
    this.primary.disabled = true;

    Generic.api
      .post(this.options.url, body)
      .then(function (answer) {
        if (commit) {
          editor.dialog.close(answer);
          return;
        }

        editor.showReview(answer || {});
      })
      .catch(function (error) {
        editor.showError(error.message);
      })
      .finally(function () {
        editor.busy = false;
        editor.primary.disabled = Boolean(
          editor.reviewed && !editor.reviewed.counts.changed
        );
      });
  };

  Editor.prototype.showError = function (message) {
    this.forget();

    var callout = el("div", "callout callout--danger", message);
    callout.setAttribute("role", "alert");
    this.review.appendChild(callout);
  };

  Editor.prototype.showReview = function (answer) {
    var counts = answer.counts || {};
    var left = (counts.refused || 0) + (counts.invalid || 0);
    var changed = counts.changed || 0;
    var callout = el(
      "div",
      "callout " + (changed ? (left ? "callout--warning" : "callout--info") : "callout--warning")
    );
    var figures = el("ul", "bulk-edit__counts");

    this.review.textContent = "";

    callout.appendChild(
      el(
        "p",
        "bulk-edit__headline",
        changed ? answer.message : t("Nothing would change.")
      )
    );

    function figure(count, singular, plural) {
      if (!count) {
        return;
      }

      figures.appendChild(
        el("li", "", Generic.format(Generic.nt(singular, plural, count), { count: count }))
      );
    }

    figure(
      counts.unchanged,
      "%(count)s already has these values.",
      "%(count)s already have these values."
    );
    figure(
      left,
      "%(count)s will be left as it is:",
      "%(count)s will be left as they are:"
    );

    if (figures.childNodes.length) {
      callout.appendChild(figures);
    }

    if ((answer.problems || []).length) {
      var list = el("ul", "bulk-edit__problems");

      answer.problems.forEach(function (problem) {
        var item = el("li");
        var name =
          problem.url && Generic.isSafeUrl(problem.url)
            ? el("a", "", problem.label)
            : el("strong", "", problem.label);

        if (name.tagName === "A") {
          name.href = problem.url;
          name.target = "_blank";
          name.rel = "noopener";
        }

        item.append(
          name,
          el("span", "bulk-edit__reason", (problem.messages || []).join(" "))
        );
        list.appendChild(item);
      });

      if (answer.moreProblems) {
        list.appendChild(el("li", "muted", t("And others.")));
      }

      callout.appendChild(list);
    }

    this.review.appendChild(callout);
    this.reviewed = answer;

    if (changed) {
      this.primary.lastChild.textContent = Generic.format(
        t("Apply to %(count)s"),
        { count: changed }
      );
      this.primary.disabled = false;
      this.primary.focus();
    } else {
      this.primary.disabled = true;
    }
  };

  function open(options) {
    var dialog = Generic.dialogs.open({
      title: options.title || t("Edit the selection"),
      icon: "edit_note",
      wide: true,
      persistent: true
    });
    var loading = el("div", "loading");

    loading.append(el("span", "spinner"), document.createTextNode(t("Loading\u2026")));
    dialog.body.appendChild(loading);

    Generic.api
      .get(options.url.split("?")[0])
      .then(function (schema) {
        loading.remove();

        if (!schema || !(schema.fields || []).length) {
          dialog.body.appendChild(
            el("p", "muted", t("There is nothing you may change here."))
          );
          return;
        }

        new Editor(options, schema, dialog);
      })
      .catch(function (error) {
        loading.remove();
        dialog.body.appendChild(el("div", "callout callout--danger", error.message));
      });

    return dialog.closed.then(function (answer) {
      return answer || null;
    });
  }

  Generic.bulkEdit = { open: open };
})(window, document);

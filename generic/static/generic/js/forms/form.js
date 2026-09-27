/**
 * The schema form: a whole add or change page, drawn from JSON.
 *
 * The page hands over a configuration - where the schema is, where the
 * record lives, where to go afterwards. Everything else comes from the
 * API: the fields and how they are laid out, the inlines, the current
 * values and their labels, the validation errors.
 *
 * What the admin's change form does, it does too: fieldsets and tabs,
 * collapsible sections, Save / Save and continue / Save and add another,
 * a deletion preview, related records created in a popup, and a warning
 * before leaving with unsaved changes.
 *
 * Events, dispatched on the host element:
 *
 *   generic:form-ready    the form is drawn and filled
 *   generic:form-saved    detail: {data, created}
 *   generic:form-deleted
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var forms = Generic.forms;

  //: Message a popup posts back to the page that opened it.
  var RELATION_MESSAGE = "generic:relation-saved";

  var instances = 0;

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

  function button(label, options) {
    options = options || {};

    var node = el("button", "button" + (options.variant ? " button--" + options.variant : ""));
    node.type = options.type || "button";

    if (options.icon) {
      node.appendChild(icon(options.icon));
    }

    node.appendChild(document.createTextNode(label));

    return node;
  }

  function link(label, url, options) {
    options = options || {};

    var node = el("a", "button" + (options.variant ? " button--" + options.variant : ""));
    node.href = url;

    if (options.icon) {
      node.appendChild(icon(options.icon));
    }

    node.appendChild(document.createTextNode(label));

    return node;
  }

  function same(first, second) {
    return JSON.stringify(first) === JSON.stringify(second);
  }

  function byPosition(first, second) {
    return (first.position || 0) - (second.position || 0);
  }

  var TEXTUAL = { text: 1, textarea: 1, email: 1, url: 1, slug: 1 };

  function isFile(value) {
    return typeof File !== "undefined" && value instanceof File;
  }

  /**
   * What is sent: the payload itself, as JSON - or, when a file was
   * chosen, a multipart body. Its `_payload` part is the very JSON
   * that would have been sent without files (the inline rows too, the
   * files left out); each file is a part of its own, named by its
   * field. A removed file stays in the JSON, as null.
   */
  function withFiles(payload) {
    var json = {};
    var files = [];

    Object.keys(payload).forEach(function (name) {
      if (isFile(payload[name])) {
        files.push(name);
      } else {
        json[name] = payload[name];
      }
    });

    if (!files.length) {
      return payload;
    }

    var body = new FormData();
    body.append("_payload", JSON.stringify(json));

    files.forEach(function (name) {
      body.append(name, payload[name], payload[name].name);
    });

    return body;
  }

  function SchemaForm(host, config) {
    instances += 1;

    this.host = host;
    this.config = config || {};
    this.id = host.id || "schema-form-" + instances;
    this.mode = this.config.mode || "update";
    this.readOnly = Boolean(this.config.readOnly);
    this.embedded = Boolean(this.config.embedded);
    this.fields = new Map();
    this.inlines = new Map();
    this.tabs = [];
    this.objectData = {};
    this.initialValues = {};
    this.dirty = false;
    this.saving = false;
    this.relationRequests = new Map();
    this.listeners = [];

    this.load();
  }

  SchemaForm.prototype.listen = function (target, type, handler) {
    target.addEventListener(type, handler);
    this.listeners.push([target, type, handler]);
  };

  /* -- Loading ------------------------------------------------------------ */

  SchemaForm.prototype.load = function () {
    var self = this;
    var config = this.config;
    var requests = [
      Generic.api.get(Generic.api.buildUrl(config.schemaUrl, { mode: this.mode }))
    ];

    if (this.mode === "update" && config.objectUrl) {
      requests.push(Generic.api.get(config.objectUrl));
    }

    Promise.all(requests)
      .then(function (results) {
        self.schema = results[0] || {};
        self.objectData = results[1] || {};
        self.render();
        self.populate();
        self.snapshot();
        self.host.dispatchEvent(
          new CustomEvent("generic:form-ready", {
            bubbles: true,
            detail: { form: self }
          })
        );
      })
      .catch(function (error) {
        var box = el("div", "callout callout--danger", error.message || t("The form could not be loaded."));
        box.setAttribute("role", "alert");
        self.host.replaceChildren(box);
      });
  };

  /* -- Drawing ---------------------------------------------------------- */

  SchemaForm.prototype.render = function () {
    var self = this;
    var schema = this.schema;
    var form = el("form", "schema-form");

    form.id = this.id;
    form.noValidate = true;
    form.classList.toggle("schema-form--embedded", this.embedded);
    form.classList.toggle("is-read-only", this.readOnly);
    this.form = form;

    this.message = el("div", "form-errors");
    this.message.hidden = true;
    this.message.setAttribute("role", "alert");
    form.appendChild(this.message);

    var sections = (schema.sections || []).slice().sort(byPosition);
    var inlineDefinitions = (schema.inlines || []).slice().sort(byPosition);
    var bySection = {};

    (schema.fields || []).forEach(function (field) {
      // Carried with the record, never drawn: its own key.
      if (field.hidden) {
        return;
      }

      var name = field.section || "general";
      (bySection[name] = bySection[name] || []).push(field);
    });

    // A field placed in a section nobody declared still shows.
    var declared = sections.map(function (section) {
      return section.name;
    });

    Object.keys(bySection).forEach(function (name) {
      if (declared.indexOf(name) === -1) {
        sections.push({ name: name, title: "", position: 999 });
      }
    });

    var tabbed =
      sections.some(function (section) {
        return section.tab && bySection[section.name];
      }) ||
      inlineDefinitions.some(function (definition) {
        return definition.tab;
      });

    var main = form;

    if (tabbed) {
      this.tabBar = el("div", "tabs");
      this.tabBar.setAttribute("role", "tablist");
      form.appendChild(this.tabBar);

      main = el("div", "tab-panel");
      form.appendChild(main);
      this.addTab("general", t("General"), main);
    }

    sections.forEach(function (section) {
      var fields = bySection[section.name];

      if (!fields || !fields.length) {
        return;
      }

      var fieldset = self.renderSection(section, fields);

      if (tabbed && section.tab) {
        var panel = el("div", "tab-panel");
        panel.appendChild(fieldset);
        form.appendChild(panel);
        self.addTab(section.name, section.title || section.name, panel);
      } else {
        main.appendChild(fieldset);
      }
    });

    inlineDefinitions.forEach(function (definition) {
      var inline = new forms.Inline(definition, self);
      self.inlines.set(definition.name, inline);

      if (tabbed && definition.tab) {
        var panel = el("div", "tab-panel");
        panel.appendChild(inline.root);
        form.appendChild(panel);
        self.addTab("inline-" + definition.name, definition.title, panel);
      } else {
        main.appendChild(inline.root);
      }
    });

    var submitRow = this.renderSubmitRow();

    if (submitRow) {
      form.appendChild(submitRow);
    }

    this.host.replaceChildren(form);

    // Select2 measures its control, so it can only start once the
    // select is in the document.
    this.fields.forEach(function (entry) {
      entry.widget.mount();
    });

    if (tabbed) {
      this.selectTab(this.initialTab());
    }

    this.bind();
  };

  SchemaForm.prototype.renderSection = function (section, fields) {
    var self = this;
    var fieldset = el("fieldset", "fieldset");
    fieldset.dataset.section = section.name;

    if (section.title) {
      var legend = el("legend", "fieldset__title");

      if (section.collapsed) {
        fieldset.dataset.collapsible = "true";
        fieldset.classList.add("is-collapsed");

        var toggle = el("button", "fieldset__toggle", section.title);
        toggle.type = "button";
        toggle.setAttribute("aria-expanded", "false");
        toggle.addEventListener("click", function () {
          var collapsed = fieldset.classList.toggle("is-collapsed");
          toggle.setAttribute("aria-expanded", String(!collapsed));
        });
        legend.appendChild(toggle);
      } else {
        legend.textContent = section.title;
      }

      fieldset.appendChild(legend);
    }

    if (section.description) {
      fieldset.appendChild(el("p", "fieldset__description", section.description));
    }

    var grid = el("div", "sf-grid");

    fields.forEach(function (field) {
      grid.appendChild(self.renderField(field));
    });

    fieldset.appendChild(grid);

    return fieldset;
  };

  SchemaForm.prototype.renderField = function (field) {
    var box = el("div", "sf-field");
    box.dataset.field = field.name;
    box.style.setProperty("--field-width", String(field.width || 12));

    var readOnly = this.readOnly || Boolean(field.readOnly);
    var widget = forms.widgets.create(field, { readOnly: readOnly, form: this });
    var id = this.id + "-" + field.name;

    if (widget.focus) {
      widget.focus.id = id;
    }

    var isSwitch = !readOnly && field.type === "boolean";

    if (!isSwitch) {
      var label = el("label", "sf-label", field.label || field.name);
      label.htmlFor = id;

      if (field.required && !readOnly) {
        var star = el("span", "sf-required", "*");
        star.setAttribute("aria-hidden", "true");
        label.appendChild(star);
      }

      box.appendChild(label);
    }

    box.appendChild(this.wrapRelation(field, widget, readOnly));

    if (field.helpText) {
      var help = el("div", "sf-help", field.helpText);
      help.id = id + "-help";
      box.appendChild(help);

      if (widget.focus && widget.focus.setAttribute) {
        widget.focus.setAttribute("aria-describedby", help.id);
      }
    }

    if (field.choicesTruncated && !readOnly) {
      box.appendChild(
        el("div", "sf-help", t("Only the first options are listed here."))
      );
    }

    var errors = el("ul", "sf-errors");
    box.appendChild(errors);

    this.fields.set(field.name, {
      field: field,
      widget: widget,
      box: box,
      errors: errors,
      readOnly: readOnly
    });

    return box;
  };

  /**
   * Add the admin's "+" and pencil beside a relation: create the related
   * record, or edit the selected one, in a popup.
   */
  SchemaForm.prototype.wrapRelation = function (field, widget, readOnly) {
    var self = this;
    var canCreate = Boolean(field.relatedCreateUrl);
    var canEdit = Boolean(field.relatedUpdateUrl) && !widget.multiple;

    if (readOnly || (!canCreate && !canEdit) || this.config.popup) {
      return widget.root;
    }

    var wrapper = el("div", "related-control");
    var actions = el("div", "related-control__actions");

    wrapper.append(widget.root, actions);

    if (canEdit) {
      var edit = el("button", "icon-button icon-button--sm");
      edit.type = "button";
      edit.title = Generic.format(t("Edit the selected %(name)s"), {
        name: field.relatedLabel || field.label
      });
      edit.setAttribute("aria-label", edit.title);
      edit.appendChild(icon("edit", "icon--sm"));
      edit.addEventListener("click", function () {
        self.openRelation(field, widget, "update");
      });
      actions.appendChild(edit);
    }

    if (canCreate) {
      var add = el("button", "icon-button icon-button--sm");
      add.type = "button";
      add.title = Generic.format(t("Add another %(name)s"), {
        name: field.relatedLabel || field.label
      });
      add.setAttribute("aria-label", add.title);
      add.appendChild(icon("add", "icon--sm"));
      add.addEventListener("click", function () {
        self.openRelation(field, widget, "create");
      });
      actions.appendChild(add);
    }

    return wrapper;
  };

  SchemaForm.prototype.renderSubmitRow = function () {
    var self = this;
    var config = this.config;
    var row = el("div", "submit-row");
    var start = el("div", "submit-row__start");
    var end = el("div", "submit-row__end");

    this.status = el("span", "submit-row__status");
    this.status.setAttribute("aria-live", "polite");
    this.buttons = [];

    if (this.readOnly) {
      if (this.embedded || !config.listUrl) {
        return null;
      }

      end.appendChild(link(t("Back to the list"), config.listUrl, { icon: "arrow_back" }));
      row.append(start, end);

      return row;
    }

    if (this.mode === "update" && config.deleteUrl && config.deletePreviewUrl) {
      var remove = button(t("Delete"), { icon: "delete", variant: "danger-ghost" });
      remove.addEventListener("click", function () {
        self.remove();
      });
      start.appendChild(remove);
    }

    start.appendChild(this.status);

    var standalone = !this.embedded && !config.popup;

    // Cancel goes back where the user came from, or to the list.
    var back = config.returnUrl || config.listUrl;

    if (standalone && back) {
      end.appendChild(link(t("Cancel"), back, { variant: "ghost" }));
    }

    if (standalone && config.addUrl) {
      var another = button(t("Save and add another"));
      another.addEventListener("click", function () {
        self.save("another");
      });
      end.appendChild(another);
      this.buttons.push(another);
    }

    // Not on a record that cannot be changed once written: there would
    // be nothing to continue with.
    if (standalone && (this.mode !== "create" || config.changeUrlTemplate)) {
      var keep = button(t("Save and continue editing"));
      keep.addEventListener("click", function () {
        self.save("continue");
      });
      end.appendChild(keep);
      this.buttons.push(keep);
    }

    var save = button(this.schema.submitLabel || t("Save"), {
      icon: "check",
      variant: "primary",
      type: "submit"
    });
    end.appendChild(save);
    this.buttons.push(save);

    row.append(start, end);

    return row;
  };

  /* -- Tabs --------------------------------------------------------------- */

  SchemaForm.prototype.addTab = function (name, label, panel) {
    var self = this;
    var tab = el("button", "tab");
    var badge = el("span", "badge-count");

    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.dataset.tab = name;
    badge.hidden = true;
    tab.append(el("span", "", label), badge);
    panel.setAttribute("role", "tabpanel");
    panel.dataset.tab = name;

    tab.addEventListener("click", function () {
      self.selectTab(name, true);
    });

    this.tabBar.appendChild(tab);
    this.tabs.push({ name: name, tab: tab, panel: panel, badge: badge });
  };

  SchemaForm.prototype.selectTab = function (name, remember) {
    var found = this.tabs.some(function (entry) {
      return entry.name === name;
    });

    if (!found && this.tabs.length) {
      name = this.tabs[0].name;
    }

    this.tabs.forEach(function (entry) {
      var active = entry.name === name;
      entry.tab.setAttribute("aria-selected", String(active));
      entry.panel.hidden = !active;
    });

    if (remember && !this.embedded && window.history.replaceState) {
      window.history.replaceState(null, "", "#tab-" + name);
    }
  };

  SchemaForm.prototype.initialTab = function () {
    var hash = window.location.hash || "";

    return hash.indexOf("#tab-") === 0 ? hash.slice(5) : "general";
  };

  SchemaForm.prototype.updateTabBadges = function () {
    this.tabs.forEach(function (entry) {
      var count = entry.panel.querySelectorAll(
        ".sf-field.has-error, .inline-cell.has-error, .inline-group__errors > div"
      ).length;

      entry.badge.hidden = count === 0;
      entry.badge.textContent = String(count);
    });
  };

  /* -- Values ----------------------------------------------------------- */

  SchemaForm.prototype.populate = function () {
    var self = this;
    var data = this.objectData || {};
    var labels = data._display || {};
    var initial = this.config.initial || {};

    this.fields.forEach(function (entry, name) {
      var value;

      if (self.mode === "update") {
        value = data[name];
      } else if (Object.prototype.hasOwnProperty.call(initial, name)) {
        value = initial[name];
      } else {
        value = entry.field.default;
      }

      entry.widget.set(value === undefined ? null : value, labels[name]);
    });

    var rows = data._inlines || {};

    this.inlines.forEach(function (inline, name) {
      inline.populate(rows[name] || []);
    });
  };

  /**
   * A raw control value as the API should receive it.
   *
   * `undefined` means "leave it out": an optional number left empty is
   * better not sent than sent as an invalid empty string, so the model
   * default applies.
   */
  SchemaForm.prototype.normalize = function (field, raw) {
    // A file nobody touched is not sent, which the API reads as "keep".
    if (raw === undefined || raw === forms.FILE_UNCHANGED) {
      return undefined;
    }

    if (raw === "" || raw === null) {
      if (field.allowNull) {
        return null;
      }

      if (TEXTUAL[field.widget] || TEXTUAL[field.type]) {
        return "";
      }

      return field.required ? "" : undefined;
    }

    return raw;
  };

  SchemaForm.prototype.values = function () {
    var self = this;
    var values = {};

    this.fields.forEach(function (entry, name) {
      if (entry.readOnly) {
        return;
      }

      var value = self.normalize(entry.field, entry.widget.get());

      if (value !== undefined) {
        values[name] = value;
      }
    });

    return values;
  };

  SchemaForm.prototype.changedValues = function () {
    var current = this.values();
    var initial = this.initialValues;
    var changed = {};

    Object.keys(current).forEach(function (name) {
      if (!same(current[name], initial[name])) {
        changed[name] = current[name];
      }
    });

    return changed;
  };

  SchemaForm.prototype.snapshot = function () {
    this.initialValues = this.values();
    this.setDirty(false);
  };

  SchemaForm.prototype.computeDirty = function () {
    if (!same(this.values(), this.initialValues)) {
      return true;
    }

    var dirty = false;

    this.inlines.forEach(function (inline) {
      dirty = dirty || inline.isDirty();
    });

    return dirty;
  };

  SchemaForm.prototype.updateDirty = function () {
    if (this.readOnly || !this.form) {
      return;
    }

    var dirty = this.computeDirty();

    if (dirty !== this.dirty) {
      this.setDirty(dirty);
    }
  };

  SchemaForm.prototype.setDirty = function (dirty) {
    this.dirty = dirty;

    if (this.form) {
      this.form.classList.toggle("is-dirty", dirty);
    }

    if (this.status && !this.saving) {
      this.status.textContent = dirty ? t("Unsaved changes") : "";
    }
  };

  /* -- Behaviour -------------------------------------------------------- */

  SchemaForm.prototype.bind = function () {
    var self = this;

    this.form.addEventListener("submit", function (event) {
      event.preventDefault();
      self.save("save");
    });

    ["input", "change", "generic:change"].forEach(function (type) {
      self.form.addEventListener(type, function () {
        self.updateDirty();
      });
    });

    this.listen(window, "beforeunload", function (event) {
      if (self.dirty && !self.saving) {
        event.preventDefault();
        event.returnValue = "";
      }
    });

    this.listen(window, "message", function (event) {
      self.handleRelationMessage(event);
    });

    // Ctrl+S saves and stays, as in an editor.
    this.listen(document, "keydown", function (event) {
      if (
        self.readOnly ||
        !(event.ctrlKey || event.metaKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return;
      }

      var several = document.querySelectorAll(".schema-form").length > 1;

      if (several && !self.form.contains(document.activeElement)) {
        return;
      }

      event.preventDefault();
      self.save(self.embedded || self.config.popup ? "save" : "continue");
    });
  };

  /* -- Saving ------------------------------------------------------------- */

  SchemaForm.prototype.setSaving = function (saving) {
    this.saving = saving;
    this.form.setAttribute("aria-busy", String(saving));

    this.buttons.forEach(function (control) {
      control.disabled = saving;
    });

    if (this.status) {
      this.status.textContent = saving
        ? t("Saving\u2026")
        : this.dirty
          ? t("Unsaved changes")
          : "";
    }
  };

  SchemaForm.prototype.validateLocally = function () {
    var invalid = 0;

    this.fields.forEach(function (entry) {
      if (entry.readOnly || typeof entry.widget.validate !== "function") {
        return;
      }

      var message = entry.widget.validate();

      if (message) {
        entry.box.classList.add("has-error");
        entry.errors.appendChild(el("li", "", message));
        invalid += 1;
      }
    });

    return invalid;
  };

  SchemaForm.prototype.save = function (intent) {
    var self = this;

    if (this.saving || this.readOnly) {
      return;
    }

    this.clearErrors();

    if (this.validateLocally()) {
      this.showMessage(t("Please correct the errors below."), []);
      return;
    }

    var create = this.mode === "create";
    var payload = create ? this.values() : this.changedValues();
    var rows = {};

    this.inlines.forEach(function (inline, name) {
      var collected = inline.collect(!create);

      if (collected.length) {
        rows[name] = collected;
      }
    });

    if (Object.keys(rows).length) {
      payload._inlines = rows;
    }

    if (!create && !Object.keys(payload).length) {
      // Nothing changed: "Save" still means "done here", as in the
      // admin; the other buttons have nothing to do.
      var back = this.config.returnUrl || this.config.listUrl;

      if (intent === "save" && !this.embedded && back) {
        this.leave(back);
      } else {
        Generic.toast(t("There is nothing to save."), "info");
      }

      return;
    }

    this.setSaving(true);

    var body = withFiles(payload);
    var request = create
      ? Generic.api.post(this.config.collectionUrl, body)
      : Generic.api.patch(this.config.objectUrl, body);

    request
      .then(function (data) {
        self.setSaving(false);
        self.saved(data || {}, intent, create);
      })
      .catch(function (error) {
        self.setSaving(false);
        self.failed(error);
      });
  };

  SchemaForm.prototype.saved = function (data, intent, created) {
    var config = this.config;
    var name = data._label || config.objectLabel || config.label || t("The record");
    var message = Generic.format(
      created ? t("\u201c%(name)s\u201d was added.") : t("\u201c%(name)s\u201d was saved."),
      { name: name }
    );
    var id = data.id !== undefined ? data.id : data.pk;

    this.setDirty(false);
    this.host.dispatchEvent(
      new CustomEvent("generic:form-saved", {
        bubbles: true,
        detail: { form: this, data: data, created: created }
      })
    );

    if (config.popup) {
      this.notifyOpener({ id: id, label: data._label || "" });
      return;
    }

    if (this.embedded) {
      this.refresh(data);
      Generic.toast(t("Saved."), "success");
      return;
    }

    if (intent === "another" && config.addUrl) {
      this.leave(config.addUrl, message);
      return;
    }

    // Ctrl+S asks to continue; a record that cannot be changed once
    // written goes where a plain save goes instead of staying on a form
    // that would write a second one.
    var canContinue = !created || Boolean(config.changeUrlTemplate);

    if (intent === "continue" && canContinue) {
      if (created && config.changeUrlTemplate && id !== undefined) {
        this.leave(config.changeUrlTemplate.replace("{id}", encodeURIComponent(id)), message);
        return;
      }

      this.refresh(data);
      Generic.toast(message, "success");
      return;
    }

    // Back where the user came from, or on to the record's own page.
    var target = config.returnUrl;

    if (!target && created && config.objectUrlTemplate && id !== undefined) {
      target = config.objectUrlTemplate.replace("{id}", encodeURIComponent(id));
    }

    this.leave(target || config.listUrl || window.location.href, message);
  };

  /** Show what the server now holds, and start counting changes anew. */
  SchemaForm.prototype.refresh = function (data) {
    this.objectData = data;
    this.populate();
    this.snapshot();
  };

  SchemaForm.prototype.leave = function (url, message) {
    if (message) {
      Generic.flash(message, "success");
    }

    this.dirty = false;
    window.location.assign(url);
  };

  SchemaForm.prototype.failed = function (error) {
    if (error && error.status === 400 && error.data && typeof error.data === "object") {
      var general = this.showErrors(error.data);

      this.showMessage(t("Please correct the errors below."), general);
      return;
    }

    Generic.toast((error && error.message) || t("The record could not be saved."), "error");
  };

  SchemaForm.prototype.clearErrors = function () {
    this.message.hidden = true;
    this.message.replaceChildren();

    this.fields.forEach(function (entry) {
      entry.box.classList.remove("has-error");
      entry.errors.replaceChildren();

      if (entry.widget.focus && entry.widget.focus.removeAttribute) {
        entry.widget.focus.removeAttribute("aria-invalid");
      }
    });

    this.inlines.forEach(function (inline) {
      inline.clearErrors();
    });

    this.updateTabBadges();
  };

  /**
   * Put each error beside its field. Returns the errors that belong to
   * no field, for the message at the top.
   */
  SchemaForm.prototype.showErrors = function (data) {
    var self = this;
    var general = [];

    Object.keys(data).forEach(function (key) {
      var value = data[key];

      if (key === "_inlines") {
        Object.keys(value || {}).forEach(function (name) {
          var inline = self.inlines.get(name);

          if (inline) {
            inline.showErrors(value[name]);
          } else {
            general = general.concat(forms.messagesOf(value[name]));
          }
        });
        return;
      }

      if (key === "non_field_errors" || key === "detail") {
        general = general.concat(forms.messagesOf(value));
        return;
      }

      var entry = self.fields.get(key);

      if (!entry) {
        forms.messagesOf(value).forEach(function (message) {
          general.push(key + ": " + message);
        });
        return;
      }

      entry.box.classList.add("has-error");

      if (entry.widget.focus && entry.widget.focus.setAttribute) {
        entry.widget.focus.setAttribute("aria-invalid", "true");
      }

      forms.messagesOf(value).forEach(function (message) {
        entry.errors.appendChild(el("li", "", message));
      });

      // An error must never hide in a folded section.
      var folded = entry.box.closest("fieldset[data-collapsible]");

      if (folded) {
        folded.classList.remove("is-collapsed");
      }
    });

    this.updateTabBadges();

    var first = this.form.querySelector(
      ".has-error input, .has-error select, .has-error textarea"
    );

    if (first) {
      var panel = first.closest(".tab-panel");

      if (panel && panel.dataset.tab) {
        this.selectTab(panel.dataset.tab);
      }

      first.focus();
    }

    return general;
  };

  /**
   * One field's own message, set - or cleared with "" - by its widget:
   * a file refused before anything is sent.
   */
  SchemaForm.prototype.setFieldError = function (name, message) {
    var entry = this.fields.get(name);

    if (!entry) {
      if (message) {
        Generic.toast(message, "error");
      }

      return;
    }

    entry.errors.replaceChildren();
    entry.box.classList.toggle("has-error", Boolean(message));

    if (entry.widget.focus && entry.widget.focus.setAttribute) {
      if (message) {
        entry.widget.focus.setAttribute("aria-invalid", "true");
      } else {
        entry.widget.focus.removeAttribute("aria-invalid");
      }
    }

    if (message) {
      entry.errors.appendChild(el("li", "", message));
    }

    this.updateTabBadges();
  };

  SchemaForm.prototype.showMessage = function (text, details) {
    this.message.replaceChildren(el("p", "", text));

    if (details && details.length) {
      var list = el("ul");

      details.forEach(function (detail) {
        list.appendChild(el("li", "", detail));
      });

      this.message.appendChild(list);
    }

    this.message.hidden = false;
    this.message.scrollIntoView({ block: "nearest", behavior: "smooth" });
  };

  /* -- Deleting ---------------------------------------------------------- */

  SchemaForm.prototype.remove = function () {
    var self = this;
    var config = this.config;

    Generic.dialogs
      .deletion({
        previewUrl: config.deletePreviewUrl,
        deleteUrl: config.deleteUrl,
        label: config.objectLabel
      })
      .then(function (deleted) {
        if (!deleted) {
          return;
        }

        self.dirty = false;
        self.host.dispatchEvent(
          new CustomEvent("generic:form-deleted", { bubbles: true, detail: { form: self } })
        );

        if (config.popup) {
          window.close();
          return;
        }

        self.leave(
          config.listUrl || "/",
          Generic.format(t("\u201c%(name)s\u201d was deleted."), {
            name: config.objectLabel || ""
          })
        );
      });
  };

  /* -- Related records in a popup ------------------------------------- */

  SchemaForm.prototype.openRelation = function (field, widget, mode) {
    var value = widget.get();

    if (mode === "update" && (!value || Array.isArray(value))) {
      Generic.toast(t("Select a record first."), "info");
      return;
    }

    var template = mode === "create" ? field.relatedCreateUrl : field.relatedUpdateUrl;
    var url = new URL(
      String(template).replace("{id}", encodeURIComponent(value || "")),
      window.location.origin
    );
    var requestId = "relation-" + Date.now() + "-" + Math.random().toString(36).slice(2);

    url.searchParams.set("_popup", "1");
    url.searchParams.set("_relation_request", requestId);

    var width = Number(field.relatedPopupWidth || 980);
    var height = Number(field.relatedPopupHeight || 760);
    var left = Math.max(0, window.screenX + (window.outerWidth - width) / 2);
    var top = Math.max(0, window.screenY + (window.outerHeight - height) / 2);
    var popup = window.open(
      url.toString(),
      requestId,
      "popup=yes,width=" + width + ",height=" + height + ",left=" + left +
        ",top=" + top + ",resizable=yes,scrollbars=yes"
    );

    if (!popup) {
      Generic.toast(t("The browser blocked the popup window."), "warning");
      return;
    }

    this.relationRequests.set(requestId, { field: field, widget: widget });
    popup.focus();
  };

  SchemaForm.prototype.handleRelationMessage = function (event) {
    if (event.origin !== window.location.origin) {
      return;
    }

    var data = event.data || {};

    if (data.type !== RELATION_MESSAGE) {
      return;
    }

    var request = this.relationRequests.get(data.requestId);

    if (!request) {
      return;
    }

    this.relationRequests.delete(data.requestId);

    var id = String(data.id);
    var labels = {};
    labels[id] = data.label || id;

    if (request.widget.multiple) {
      var current = request.widget.get() || [];

      if (current.indexOf(id) === -1) {
        current.push(id);
      }

      request.widget.set(current, labels);
    } else {
      request.widget.set(id, labels);
    }

    this.updateDirty();
    Generic.toast(
      Generic.format(t("\u201c%(name)s\u201d is selected."), { name: labels[id] }),
      "success"
    );
  };

  /** In a popup: report the saved record to the opener and close. */
  SchemaForm.prototype.notifyOpener = function (record) {
    if (window.opener && this.config.popupRequest) {
      window.opener.postMessage(
        {
          type: RELATION_MESSAGE,
          requestId: this.config.popupRequest,
          id: record.id,
          label: record.label
        },
        window.location.origin
      );
    }

    window.close();
  };

  SchemaForm.prototype.destroy = function () {
    this.listeners.forEach(function (entry) {
      entry[0].removeEventListener(entry[1], entry[2]);
    });
    this.listeners = [];

    this.fields.forEach(function (entry) {
      entry.widget.destroy();
    });

    this.inlines.forEach(function (inline) {
      inline.destroy();
    });
  };

  /* -- Start-up ------------------------------------------------------------ */

  function initialize(root) {
    var started = [];

    (root || document).querySelectorAll(".js-schema-form").forEach(function (host) {
      if (host.dataset.schemaFormReady === "true") {
        return;
      }

      var config;

      try {
        config = JSON.parse(document.getElementById(host.dataset.config).textContent);
      } catch (error) {
        host.replaceChildren(
          el("div", "callout callout--danger", t("The form configuration is missing."))
        );
        return;
      }

      host.dataset.schemaFormReady = "true";
      host.schemaForm = new SchemaForm(host, config);
      started.push(host.schemaForm);
    });

    return started;
  }

  forms.SchemaForm = SchemaForm;
  forms.initialize = initialize;

  Generic.ready(function () {
    initialize(document);
  });
})(window, document);

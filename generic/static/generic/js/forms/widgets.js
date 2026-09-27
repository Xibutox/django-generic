/**
 * Form controls, one per field type of the DRF form schema.
 *
 * Every widget has the same small surface, so the form and the inlines
 * never care which one they hold:
 *
 *   root      the element to insert
 *   focus     the element that takes focus and carries the id
 *   get()     the current value, as the API expects it
 *   set(v, labels)  show a value; labels name related records
 *   disable(bool), mount(), destroy()
 *
 * A project adds its own with `Generic.forms.registerWidget(name,
 * factory)`, selected by a field's `widget` in `form_overrides`.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var forms = (Generic.forms = Generic.forms || {});

  var INPUT_TYPES = {
    integer: "number",
    decimal: "number",
    float: "number",
    date: "date",
    datetime: "datetime-local",
    time: "time",
    email: "email",
    url: "url",
    password: "password"
  };

  var EMPTY = "\u2014";

  //: Choice lists longer than this get a searchable Select2 control.
  var SEARCHABLE_CHOICES = 7;

  var custom = {};

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

  function isEmpty(value) {
    return (
      value === null ||
      value === undefined ||
      value === "" ||
      (Array.isArray(value) && value.length === 0)
    );
  }

  function choiceLabel(field, value) {
    var choices = field.choices || [];

    for (var index = 0; index < choices.length; index += 1) {
      if (String(choices[index].value) === String(value)) {
        return choices[index].label;
      }
    }

    return value;
  }

  function formatDate(value) {
    var parts = String(value).split("-");

    if (parts.length !== 3) {
      return String(value);
    }

    var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));

    return isNaN(date.getTime())
      ? String(value)
      : date.toLocaleDateString(document.documentElement.lang || undefined);
  }

  function truthy(value) {
    return (
      value === true ||
      value === 1 ||
      value === "1" ||
      value === "true" ||
      value === "True" ||
      value === "on"
    );
  }

  /** How a value reads outside a control. */
  function displayValue(field, value, labels) {
    labels = labels || {};

    if (isEmpty(value)) {
      return EMPTY;
    }

    if (field.type === "boolean") {
      return truthy(value) ? t("Yes") : t("No");
    }

    if (Array.isArray(value)) {
      return value
        .map(function (item) {
          return labels[String(item)] || choiceLabel(field, item);
        })
        .join(", ");
    }

    if (labels[String(value)]) {
      return labels[String(value)];
    }

    if (field.choices) {
      return String(choiceLabel(field, value));
    }

    if (field.type === "datetime") {
      return Generic.formatDateTime(value);
    }

    if (field.type === "date") {
      return formatDate(value);
    }

    if (typeof value === "object") {
      return JSON.stringify(value);
    }

    return String(value);
  }

  function icon(name) {
    var node = el("span", "icon material-symbols-outlined icon--sm", name);
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  /* -- Files: shared ----------------------------------------------------
   *
   * A stored file arrives as {name, url, size}; `url` is the record's
   * own download endpoint, which checks who asks.
   */

  function isFileField(field) {
    return field.type === "file" || field.type === "image";
  }

  /** A stored file as {name, url, size}, or null when there is none. */
  function storedFile(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }

    if (typeof value === "object" && value.name) {
      return {
        name: String(value.name),
        url: value.url ? String(value.url) : "",
        size: typeof value.size === "number" ? value.size : null
      };
    }

    // A hand-written serializer may still send the storage's URL.
    var text = String(value);

    return { name: text.split("/").pop(), url: text, size: null };
  }

  var formatSize = Generic.formatSize;

  /** Whether `file` is one an `accept` attribute lets through. */
  function acceptsFile(accept, file) {
    if (!accept) {
      return true;
    }

    var name = String(file.name || "").toLowerCase();
    var type = String(file.type || "").toLowerCase();

    return accept.split(",").some(function (token) {
      token = token.trim().toLowerCase();

      if (!token) {
        return false;
      }

      if (token.charAt(0) === ".") {
        return name.length > token.length && name.slice(-token.length) === token;
      }

      if (token.slice(-2) === "/*") {
        return type.indexOf(token.slice(0, -1)) === 0;
      }

      return type === token;
    });
  }

  /** A stored file's name, linking to its download when there is one. */
  function fileLink(stored) {
    var url = stored.url && Generic.isSafeUrl(stored.url) ? stored.url : "";
    var node = el(url ? "a" : "span", "sf-file__name", stored.name);

    if (url) {
      node.href = url;
    }

    return node;
  }

  /* -- Read only -------------------------------------------------------- */

  function readonlyWidget(field) {
    var root = el("div", "sf-readonly", EMPTY);

    return {
      root: root,
      focus: root,
      readOnly: true,
      get: function () {
        return undefined;
      },
      set: function (value, labels) {
        if (isFileField(field)) {
          var stored = storedFile(value);

          root.replaceChildren();

          if (!stored) {
            root.textContent = EMPTY;
            return;
          }

          root.appendChild(fileLink(stored));

          if (stored.size !== null) {
            root.append(" ", el("span", "sf-file__size", formatSize(stored.size)));
          }

          return;
        }

        root.textContent = displayValue(field, value, labels);
      },
      disable: function () {},
      mount: function () {},
      destroy: function () {}
    };
  }

  /* -- Text, numbers, dates ---------------------------------------------- */

  function inputWidget(field, context) {
    var input = el("input", "input" + (context.compact ? " input--sm" : ""));
    var type = INPUT_TYPES[field.widget] || INPUT_TYPES[field.type] || "text";

    input.type = type;

    if (type === "password") {
      // Without this the browser offers the person filling the form
      // their own saved password, for somebody else's account.
      input.autocomplete = "new-password";
    }

    if (field.type === "integer") {
      input.step = field.step || "1";
    } else if (field.type === "float" || field.type === "decimal") {
      input.step = field.step || "any";
    }

    if (field.minimum !== undefined) {
      input.min = field.minimum;
    }

    if (field.maximum !== undefined) {
      input.max = field.maximum;
    }

    if (field.maxLength) {
      input.maxLength = field.maxLength;
    }

    if (field.placeholder) {
      input.placeholder = field.placeholder;
    }

    return {
      root: input,
      focus: input,
      get: function () {
        var value = input.value;

        if (value === "") {
          return "";
        }

        if (field.type === "integer") {
          var whole = parseInt(value, 10);
          return isNaN(whole) ? value : whole;
        }

        if (field.type === "float") {
          var number = parseFloat(value);
          return isNaN(number) ? value : number;
        }

        return value;
      },
      set: function (value) {
        if (value === null || value === undefined) {
          input.value = "";
        } else if (type === "datetime-local") {
          // The API sends the wall-clock time with its offset; the
          // control wants the wall-clock time alone.
          input.value = String(value).slice(0, 16);
        } else if (type === "time") {
          input.value = String(value).slice(0, 5);
        } else {
          input.value = String(value);
        }
      },
      disable: function (disabled) {
        input.disabled = disabled;
      },
      mount: function () {},
      destroy: function () {}
    };
  }

  function textareaWidget(field, context) {
    var textarea = el("textarea", "input");

    textarea.rows = field.rows || (context.compact ? 2 : 4);

    if (field.maxLength) {
      textarea.maxLength = field.maxLength;
    }

    if (field.placeholder) {
      textarea.placeholder = field.placeholder;
    }

    return {
      root: textarea,
      focus: textarea,
      get: function () {
        return textarea.value;
      },
      set: function (value) {
        textarea.value = value === null || value === undefined ? "" : String(value);
      },
      disable: function (disabled) {
        textarea.disabled = disabled;
      },
      mount: function () {},
      destroy: function () {}
    };
  }

  /**
   * A colour: the value as text, which may stay empty, beside a picker
   * and a preview. `form_overrides = {"color": {"widget": "color"}}`.
   */
  function colorWidget(field, context) {
    var root = el("div", "sf-color");
    var swatch = el("input", "sf-color__picker");
    var text = el("input", "input" + (context.compact ? " input--sm" : ""));

    swatch.type = "color";
    swatch.setAttribute("aria-label", t("Pick a colour"));
    text.type = "text";
    text.spellcheck = false;
    text.placeholder = field.placeholder || "#2563eb";

    if (field.maxLength) {
      text.maxLength = field.maxLength;
    }

    function sync() {
      var value = text.value.trim();

      // The picker only speaks #rrggbb; anything else stays as typed.
      if (/^#[0-9a-f]{6}$/i.test(value)) {
        swatch.value = value.toLowerCase();
      }

      root.classList.toggle("is-empty", !Generic.colors.clean(value));
      root.style.setProperty("--sf-color", Generic.colors.clean(value) || "transparent");
    }

    swatch.addEventListener("input", function () {
      text.value = swatch.value;
      sync();
      text.dispatchEvent(new Event("input", { bubbles: true }));
    });

    text.addEventListener("input", sync);
    root.append(swatch, text);

    return {
      root: root,
      focus: text,
      get: function () {
        return text.value.trim();
      },
      set: function (value) {
        text.value = value === null || value === undefined ? "" : String(value);
        sync();
      },
      validate: function () {
        var value = text.value.trim();

        return value && !Generic.colors.clean(value)
          ? t("Enter a colour, such as #2563eb.")
          : "";
      },
      disable: function (disabled) {
        text.disabled = disabled;
        swatch.disabled = disabled;
      },
      mount: function () {},
      destroy: function () {}
    };
  }

  /** JSON, edited as text and checked before it is sent. */
  function jsonWidget(field, context) {
    var widget = textareaWidget(field, context);
    var textarea = widget.root;

    textarea.classList.add("input--code");
    textarea.spellcheck = false;

    widget.set = function (value) {
      textarea.value =
        value === null || value === undefined ? "" : JSON.stringify(value, null, 2);
    };

    widget.get = function () {
      if (!textarea.value.trim()) {
        return null;
      }

      try {
        return JSON.parse(textarea.value);
      } catch (error) {
        return textarea.value;
      }
    };

    widget.validate = function () {
      if (!textarea.value.trim()) {
        return "";
      }

      try {
        JSON.parse(textarea.value);
        return "";
      } catch (error) {
        return t("This is not valid JSON.");
      }
    };

    return widget;
  }

  /* -- Boolean -------------------------------------------------------------- */

  function booleanWidget(field, context) {
    var label = el("label", "switch");
    var input = el("input");
    input.type = "checkbox";
    label.append(input, el("span", "switch__label", context.hideLabel ? "" : field.label));

    return {
      root: label,
      focus: input,
      get: function () {
        return input.checked;
      },
      set: function (value) {
        input.checked = truthy(value);
      },
      disable: function (disabled) {
        input.disabled = disabled;
      },
      mount: function () {},
      destroy: function () {}
    };
  }

  /* -- Choices and relations ------------------------------------------------
   *
   * A relation - a foreign key or a many-to-many - is always a Select2
   * control: searching the related model's autocomplete endpoint when it
   * has one, the embedded choices otherwise. A short fixed list stays a
   * plain select, which is faster to use with a keyboard.
   */

  function selectWidget(field, context) {
    var select = el("select", "input" + (context.compact ? " input--sm" : ""));
    var multiple = field.type === "multiselect" || field.widget === "multiselect";
    var relation = Boolean(field.relation || field.autocompleteUrl || field.relatedModel);
    var choices = field.choices || [];
    var enhanced = false;

    select.multiple = multiple;

    if (!multiple) {
      select.appendChild(new Option(relation ? "" : "\u2014", ""));
    }

    choices.forEach(function (choice) {
      select.appendChild(new Option(choice.label, String(choice.value)));
    });

    var searchable =
      relation || multiple || choices.length > SEARCHABLE_CHOICES;

    function mount() {
      if (!searchable || enhanced || !Generic.select2 || !Generic.select2.available()) {
        return;
      }

      Generic.select2.init(select, {
        url: field.autocompleteUrl,
        placeholder: field.placeholder,
        allowClear: !multiple && (!field.required || field.allowNull),
        disabled: select.disabled
      });
      enhanced = true;
    }

    function currentValues() {
      return Array.from(select.selectedOptions)
        .map(function (option) {
          return option.value;
        })
        .filter(function (value) {
          return value !== "";
        });
    }

    return {
      root: select,
      focus: select,
      select: select,
      multiple: multiple,
      mount: mount,
      get: function () {
        return multiple ? currentValues() : select.value;
      },
      set: function (value, labels) {
        labels = labels || {};

        var values = isEmpty(value) ? [] : Array.isArray(value) ? value : [value];
        var missing = values.filter(function (item) {
          var key = String(item);
          var option = Array.prototype.find.call(select.options, function (entry) {
            return entry.value === key;
          });

          return !labels[key] && !option;
        });

        if (Generic.select2) {
          Generic.select2.setValues(select, value, labels);
        } else {
          select.value = values.length ? String(values[0]) : "";
        }

        // A value set from the query string, or kept after a failed
        // save, may have no label yet: the endpoint names it.
        if (missing.length && field.autocompleteUrl && Generic.select2) {
          Generic.select2
            .resolveLabels(field.autocompleteUrl, missing)
            .then(function (found) {
              Object.keys(found).forEach(function (key) {
                Generic.select2.ensureOption(select, key, found[key]);
              });
              Generic.select2.refresh(select);
            });
        }
      },
      disable: function (disabled) {
        select.disabled = disabled;

        if (enhanced) {
          window.jQuery(select).prop("disabled", disabled);
        }
      },
      destroy: function () {
        if (enhanced) {
          Generic.select2.destroy(select);
        }
      }
    };
  }

  /* -- Files -------------------------------------------------------------
   *
   * What the reader did with the field is what get() says: nothing
   * (FILE_UNCHANGED, which the form leaves out of what it sends),
   * removed it (null), or chose a new file (the File itself, which the
   * form sends as a multipart part). The native chooser sits inside
   * the "Choose a file" button, out of sight but focusable: the
   * keyboard reaches it, and the field's label opens it.
   */

  var FILE_UNCHANGED = Object.freeze({ fileUnchanged: true });

  function fileWidget(field, context) {
    var root = el("div", "sf-file");
    var current = el("div", "sf-file__current");
    var chosenRow = el("div", "sf-file__chosen");
    var chosenName = el("span", "sf-file__name");
    var chosenSize = el("span", "sf-file__size");
    var actions = el("div", "sf-file__actions");
    var chooser = el("label", "button button--sm sf-file__choose");
    var chooserText = el("span");
    var input = el("input", "sf-file__input");
    var remove = el("button", "button button--sm button--danger-ghost");
    var cancel = el("button", "button button--sm button--ghost", t("Cancel"));
    var stored = null;
    var chosen = null;
    var removed = false;

    input.type = "file";

    if (field.accept) {
      input.accept = field.accept;
    }

    remove.type = "button";
    cancel.type = "button";
    chooser.append(icon("upload_file"), chooserText, input);
    chosenRow.append(
      icon("draft"),
      chosenName,
      chosenSize,
      el("span", "sf-file__note", t("Sent when you save.")),
      cancel
    );
    actions.append(chooser, remove);
    root.append(current, chosenRow, actions);

    function render() {
      current.replaceChildren();

      if (stored) {
        current.append(icon("draft"), fileLink(stored));

        if (stored.size !== null) {
          current.appendChild(el("span", "sf-file__size", formatSize(stored.size)));
        }

        if (removed) {
          current.appendChild(el("span", "sf-file__note", t("Removed when you save.")));
        } else if (chosen) {
          current.appendChild(el("span", "sf-file__note", t("Replaced when you save.")));
        }
      } else {
        current.appendChild(el("span", "sf-file__note", t("No file")));
      }

      current.hidden = !stored && Boolean(chosen);
      chosenRow.hidden = !chosen;

      if (chosen) {
        chosenName.textContent = chosen.name;
        chosenSize.textContent = formatSize(chosen.size);
      }

      chooserText.textContent = stored || chosen ? t("Replace") : t("Choose a file");
      // A file the field may go without can be taken away; a choice
      // not yet sent is dropped with Cancel instead.
      remove.hidden = !stored || Boolean(field.required) || Boolean(chosen);
      remove.textContent = removed ? t("Keep the file") : t("Remove");
      root.classList.toggle("is-removed", removed);
    }

    function report(message) {
      var form = context.form;

      if (form && typeof form.setFieldError === "function") {
        form.setFieldError(field.name, message);
      } else if (message) {
        Generic.toast(message, "error");
      }
    }

    function changed() {
      root.dispatchEvent(new CustomEvent("generic:change", { bubbles: true }));
    }

    /** Why `file` cannot be sent, or "" - the server checks it again. */
    function refusal(file) {
      if (field.maxSize && file.size > field.maxSize) {
        return Generic.format(
          t("%(name)s is too large (%(size)s): the limit is %(limit)s."),
          { name: file.name, size: formatSize(file.size), limit: formatSize(field.maxSize) }
        );
      }

      if (!acceptsFile(field.accept, file)) {
        return Generic.format(
          t("%(name)s is not a kind of file this field takes (%(accept)s)."),
          { name: file.name, accept: field.accept }
        );
      }

      return "";
    }

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];

      // Emptied at once, so choosing the same file again still counts.
      input.value = "";

      if (!file) {
        return;
      }

      var message = refusal(file);

      report(message);

      if (message) {
        return;
      }

      chosen = file;
      removed = false;
      render();
      changed();
    });

    cancel.addEventListener("click", function () {
      chosen = null;
      report("");
      render();
      changed();
      input.focus();
    });

    remove.addEventListener("click", function () {
      removed = !removed;
      render();
      changed();
    });

    render();

    return {
      root: root,
      focus: input,
      get: function () {
        if (chosen) {
          return chosen;
        }

        return removed ? null : FILE_UNCHANGED;
      },
      set: function (value) {
        stored = storedFile(value);
        chosen = null;
        removed = false;
        render();
      },
      disable: function (disabled) {
        input.disabled = disabled;
        remove.disabled = disabled;
        cancel.disabled = disabled;
        root.classList.toggle("is-disabled", disabled);
      },
      mount: function () {},
      destroy: function () {}
    };
  }

  /* -- Registry ---------------------------------------------------------------- */

  function registerWidget(name, factory) {
    custom[name] = factory;
  }

  /**
   * The widget for `field`.
   *
   * `context.readOnly` shows the value as text; `context.compact` is set
   * inside a tabular inline.
   */
  function create(field, context) {
    context = context || {};

    if (custom[field.widget]) {
      return custom[field.widget](field, context);
    }

    if (context.readOnly || field.readOnly) {
      return readonlyWidget(field);
    }

    var kind = field.widget || field.type;

    if (kind === "boolean") {
      return booleanWidget(field, context);
    }

    if (kind === "textarea") {
      return textareaWidget(field, context);
    }

    if (kind === "select" || kind === "multiselect") {
      return selectWidget(field, context);
    }

    if (kind === "json" || kind === "list" || kind === "object") {
      return jsonWidget(field, context);
    }

    if (kind === "color") {
      return colorWidget(field, context);
    }

    // A file travels beside the JSON, as a multipart part (form.js).
    if (kind === "file" || kind === "image") {
      return fileWidget(field, context);
    }

    return inputWidget(field, context);
  }

  forms.widgets = {
    create: create,
    displayValue: displayValue,
    isEmpty: isEmpty,
    truthy: truthy,
    acceptsFile: acceptsFile
  };
  forms.FILE_UNCHANGED = FILE_UNCHANGED;
  forms.registerWidget = registerWidget;
})(window, document);

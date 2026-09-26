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
        if ((field.type === "file" || field.type === "image") && value) {
          root.replaceChildren();

          if (Generic.isSafeUrl(value)) {
            var link = el("a", "", String(value).split("/").pop());
            link.href = value;
            link.target = "_blank";
            link.rel = "noopener";
            root.appendChild(link);
            return;
          }
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

    // Uploads are not sent as JSON; the field is shown, not edited.
    if (kind === "file" || kind === "image") {
      return readonlyWidget(field);
    }

    return inputWidget(field, context);
  }

  forms.widgets = {
    create: create,
    displayValue: displayValue,
    isEmpty: isEmpty,
    truthy: truthy
  };
  forms.registerWidget = registerWidget;
})(window, document);

/**
 * Modal dialogs: confirm, prompt, and the deletion preview.
 *
 * Built on the native <dialog> element, which traps focus, closes on
 * Escape and dims the page by itself. Each call returns a promise, so a
 * caller reads like a plain question:
 *
 *   Generic.dialogs.confirm({ title: "Close 3 tickets?" })
 *     .then(function (yes) { ... });
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
    var node = el("span", "icon material-symbols-outlined", name);
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  function button(label, variant, iconName) {
    var node = el("button", "button" + (variant ? " button--" + variant : ""));
    node.type = "button";

    if (iconName) {
      node.appendChild(icon(iconName));
    }

    node.appendChild(document.createTextNode(label));

    return node;
  }

  /**
   * Build and open one dialog. The element removes itself once closed,
   * so nothing accumulates in the page.
   */
  function open(options) {
    var dialog = el("dialog", "dialog" + (options.wide ? " dialog--wide" : ""));
    var header = el("div", "dialog__header");
    var title = el("h2", "dialog__title");

    if (options.icon) {
      title.appendChild(icon(options.icon));
    }

    title.appendChild(document.createTextNode(options.title || ""));

    var close = el("button", "icon-button icon-button--sm");
    close.type = "button";
    close.setAttribute("aria-label", t("Close"));
    close.appendChild(icon("close"));

    header.append(title, close);

    var body = el("div", "dialog__body");
    var footer = el("div", "dialog__footer");

    dialog.append(header, body, footer);
    document.body.appendChild(dialog);

    var controller = {
      dialog: dialog,
      body: body,
      footer: footer,
      result: undefined,
      close: function (result) {
        controller.result = result;

        if (dialog.open) {
          dialog.close();
        }
      }
    };

    close.addEventListener("click", function () {
      controller.close(undefined);
    });

    // A click on the dimmed backdrop lands on the dialog itself.
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog && !options.persistent) {
        controller.close(undefined);
      }
    });

    controller.closed = new Promise(function (resolve) {
      dialog.addEventListener("close", function () {
        dialog.remove();
        resolve(controller.result);
      });
    });

    dialog.showModal();

    return controller;
  }

  /** Ask a yes or no question. Resolves to a boolean. */
  function confirm(options) {
    options = options || {};

    var dialog = open({
      title: options.title || t("Are you sure?"),
      icon: options.icon || (options.variant === "danger" ? "warning" : "help")
    });

    if (options.message) {
      dialog.body.appendChild(el("p", "", options.message));
    }

    var cancel = button(options.cancelLabel || t("Cancel"), "ghost");
    var accept = button(
      options.confirmLabel || t("Confirm"),
      options.variant === "danger" ? "danger" : "primary",
      options.confirmIcon
    );

    cancel.addEventListener("click", function () {
      dialog.close(false);
    });

    accept.addEventListener("click", function () {
      dialog.close(true);
    });

    dialog.footer.append(cancel, accept);
    accept.focus();

    return dialog.closed.then(function (result) {
      return result === true;
    });
  }

  /**
   * Ask for a line of text. Resolves to `{value, checked}`, or null.
   *
   * `checkbox` adds one option under the field - "use as default" when
   * saving a table view, for instance.
   */
  function prompt(options) {
    options = options || {};

    var dialog = open({ title: options.title || "", icon: options.icon });
    var form = el("form", "stack");
    var label = el("label", "sf-label", options.label || "");
    var input = el("input", "input");

    input.type = "text";
    input.value = options.value || "";
    input.placeholder = options.placeholder || "";
    input.maxLength = options.maxLength || 80;
    input.required = true;

    var field = el("div", "sf-field");
    field.append(label, input);
    form.appendChild(field);

    var checkbox = null;

    if (options.checkbox) {
      var toggle = el("label", "switch");
      checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(options.checkbox.checked);
      toggle.append(checkbox, el("span", "switch__label", options.checkbox.label));
      form.appendChild(toggle);
    }

    dialog.body.appendChild(form);

    var cancel = button(t("Cancel"), "ghost");
    var accept = button(options.confirmLabel || t("Save"), "primary");

    function submit(event) {
      if (event) {
        event.preventDefault();
      }

      var value = input.value.trim();

      if (!value) {
        input.focus();
        return;
      }

      dialog.close({ value: value, checked: checkbox ? checkbox.checked : false });
    }

    cancel.addEventListener("click", function () {
      dialog.close(null);
    });
    accept.addEventListener("click", submit);
    form.addEventListener("submit", submit);

    dialog.footer.append(cancel, accept);
    input.focus();
    input.select();

    return dialog.closed.then(function (result) {
      return result || null;
    });
  }

  /**
   * A few values asked for at once - a transition's resolution note:
   * `fields` = [{name, label, value, required, multiline, maxLength}]. Resolves
   * to {name: value}, or null when cancelled.
   */
  function fields(options) {
    options = options || {};

    var dialog = open({ title: options.title || "", icon: options.icon });
    var form = el("form", "stack");
    var inputs = [];

    if (options.message) {
      form.appendChild(el("p", "muted", options.message));
    }

    (options.fields || []).forEach(function (spec, index) {
      var id = "dialog-field-" + index;
      var field = el("div", "sf-field");
      var label = el("label", "sf-label", spec.label || spec.name);
      var input = el(spec.multiline ? "textarea" : "input", "input");

      label.htmlFor = id;
      input.id = id;
      input.name = spec.name;
      input.required = Boolean(spec.required);
      input.value = spec.value || "";

      if (spec.multiline) {
        input.rows = 4;
      } else {
        input.type = "text";
      }

      if (spec.maxLength) {
        input.maxLength = spec.maxLength;
      }

      field.append(label, input);
      form.appendChild(field);
      inputs.push(input);
    });

    dialog.body.appendChild(form);

    var cancel = button(t("Cancel"), "ghost");
    var accept = button(
      options.confirmLabel || t("Save"),
      options.variant === "danger" ? "danger" : "primary"
    );

    function submit(event) {
      if (event) {
        event.preventDefault();
      }

      var missing = inputs.find(function (input) {
        return input.required && !input.value.trim();
      });

      if (missing) {
        missing.focus();
        return;
      }

      var values = {};

      inputs.forEach(function (input) {
        values[input.name] = input.value.trim();
      });
      dialog.close(values);
    }

    cancel.addEventListener("click", function () {
      dialog.close(null);
    });
    accept.addEventListener("click", submit);
    form.addEventListener("submit", submit);

    dialog.footer.append(cancel, accept);

    if (inputs.length) {
      inputs[0].focus();
    }

    return dialog.closed.then(function (result) {
      return result || null;
    });
  }

  /* -- Deletion ---------------------------------------------------------
   *
   * The admin's confirmation page, as a dialog: what the cascade would
   * take with it, or what protects the record, straight from the API's
   * deletion-preview endpoint.
   */

  /** Draw Django's nested collector output: an object, then its children. */
  function renderTree(nodes) {
    var list = el("ul", "deletion-tree");
    var last = null;

    (nodes || []).forEach(function (node) {
      if (Array.isArray(node)) {
        (last || list).appendChild(renderTree(node));
        return;
      }

      var item = el("li");
      item.append(
        el("span", "deletion-tree__model", node.modelLabel || ""),
        el("span", "deletion-tree__label", node.label || "")
      );
      list.appendChild(item);
      last = item;
    });

    return list;
  }

  function countNodes(nodes, counts) {
    (nodes || []).forEach(function (node) {
      if (Array.isArray(node)) {
        countNodes(node, counts);
        return;
      }

      var key = node.modelLabelPlural || node.modelLabel || "";
      counts[key] = (counts[key] || 0) + 1;
    });

    return counts;
  }

  /**
   * Preview, confirm and delete one record.
   *
   * Resolves to true once the record is gone, false otherwise. A refusal
   * from the server - a relation appeared in the meantime - is shown in
   * the dialog rather than lost.
   */
  function deletion(options) {
    options = options || {};

    var dialog = open({
      title: options.title || t("Delete this record?"),
      icon: "delete",
      wide: true
    });

    var loading = el("div", "loading");
    loading.append(el("span", "spinner"), document.createTextNode(t("Checking what depends on it\u2026")));
    dialog.body.appendChild(loading);

    var message = el("div", "callout callout--danger");
    message.hidden = true;

    var cancel = button(t("Cancel"), "ghost");
    var accept = button(t("Yes, delete"), "danger", "delete");
    accept.disabled = true;

    cancel.addEventListener("click", function () {
      dialog.close(false);
    });

    dialog.footer.append(cancel, accept);

    function fail(error) {
      message.textContent = error.message || t("The record could not be deleted.");
      message.hidden = false;
    }

    Generic.api
      .get(options.previewUrl)
      .then(function (preview) {
        loading.remove();
        preview = preview || {};

        var label = (preview.object && preview.object.label) || options.label || "";

        if (preview.canDelete) {
          dialog.body.appendChild(
            el(
              "p",
              "lead",
              Generic.format(
                t("\u201c%(name)s\u201d and everything below will be deleted."),
                { name: label }
              )
            )
          );

          var counts = countNodes(preview.nested, {});
          var summary = Object.keys(counts).map(function (key) {
            return counts[key] + " \u00d7 " + key;
          });

          if (summary.length) {
            dialog.body.appendChild(el("p", "muted", summary.join(" \u00b7 ")));
          }

          dialog.body.appendChild(renderTree(preview.nested));
          accept.disabled = false;
          accept.focus();
        } else {
          var callout = el("div", "callout callout--danger");
          callout.appendChild(
            el(
              "p",
              "",
              Generic.format(
                t("\u201c%(name)s\u201d cannot be deleted: these records depend on it and are protected."),
                { name: label }
              )
            )
          );
          callout.appendChild(renderTree(preview.protected));
          dialog.body.appendChild(callout);
          accept.hidden = true;
          cancel.textContent = t("Close");
        }

        dialog.body.appendChild(message);
      })
      .catch(function (error) {
        loading.remove();
        dialog.body.appendChild(message);
        fail(error);
      });

    accept.addEventListener("click", function () {
      accept.disabled = true;

      Generic.api
        .delete(options.deleteUrl)
        .then(function () {
          dialog.close(true);
        })
        .catch(function (error) {
          accept.disabled = false;
          fail(error);
        });
    });

    return dialog.closed.then(function (result) {
      return result === true;
    });
  }

  Generic.dialogs = {
    fields: fields,
    confirm: confirm,
    deletion: deletion,
    open: open,
    prompt: prompt,
    renderTree: renderTree
  };
})(window, document);

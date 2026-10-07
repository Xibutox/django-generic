/**
 * A value typed as a summary page types it (generic.sites.summary:
 * describe_entry), drawn as an element: text, a number, a date, a
 * boolean, a choice, links, coloured tags, a file.
 *
 * Shared by everything drawing such values outside the summary page:
 * the tree (tree.js), the dashboard's cards (dashboard.js), the
 * calendar (calendar.js).
 *
 *   Generic.values.render(entry)  -> an element
 *   Generic.values.tag(item)      -> one coloured tag
 *
 * Every value reaches the page through textContent, every address
 * through Generic.isSafeUrl, every colour through Generic.colors.clean.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  function el(tag, className, text) {
    var element = document.createElement(tag);

    if (className) {
      element.className = className;
    }

    if (text !== undefined && text !== null) {
      element.textContent = String(text);
    }

    return element;
  }

  function icon(name, extra) {
    var element = el("span", "icon material-symbols-outlined icon--sm" + (extra ? " " + extra : ""), name);

    element.setAttribute("aria-hidden", "true");

    return element;
  }

  function link(url, text) {
    if (url && Generic.isSafeUrl(url)) {
      var anchor = el("a", "", text);

      anchor.href = url;

      return anchor;
    }

    return el("span", "", text);
  }

  /* -- Values, typed as a summary page types them ----------------------- */

  function tag(entry) {
    var colors = Generic.colors;
    var background = colors.clean(entry.background);
    var color = colors.clean(entry.color);
    var element = link(entry.url, entry.label);

    element.className = background ? "tag tag--solid" : "tag";

    if (background) {
      element.style.setProperty("--tag-background", background);
      element.style.setProperty("--tag-text", color || colors.readableOn(background));
    } else if (color) {
      element.style.setProperty("--tag-color", color);
    }

    if (entry.title) {
      element.title = entry.title;
    }

    return element;
  }

  function value(entry) {
    entry = entry || { empty: true };

    var wrapper = el("span", "typed-value typed-value--" + (entry.type || "text"));

    if (entry.empty) {
      wrapper.appendChild(el("span", "muted", "\u2014"));
      return wrapper;
    }

    switch (entry.type) {
      case "boolean":
        var yes = Boolean(entry.value);
        var flag = el("span", "dt-boolean " + (yes ? "dt-boolean--yes" : "dt-boolean--no"));

        flag.appendChild(icon(yes ? "check_circle" : "cancel"));
        flag.appendChild(el("span", "", yes ? t("Yes") : t("No")));
        wrapper.appendChild(flag);
        break;
      case "choice":
        wrapper.appendChild(el("span", "badge", entry.display));
        break;
      case "link":
      case "url":
      case "file":
        wrapper.appendChild(link(entry.url, entry.display));
        break;
      case "email":
        wrapper.appendChild(link("mailto:" + entry.display, entry.display));
        break;
      case "links":
        (entry.items || []).forEach(function (item, index) {
          if (index) {
            wrapper.appendChild(document.createTextNode(", "));
          }
          wrapper.appendChild(link(item.url, item.label));
        });
        break;
      case "tags":
        (entry.items || []).forEach(function (item) {
          wrapper.appendChild(tag(item));
        });
        break;
      default:
        wrapper.textContent = entry.display === undefined ? "" : String(entry.display);
    }

    if (entry.more) {
      wrapper.appendChild(el("span", "muted", " +" + entry.more));
    }

    return wrapper;
  }

  Generic.values = { el: el, icon: icon, link: link, tag: tag, render: value };
})(window, document);

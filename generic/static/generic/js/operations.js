/**
 * Operations: what the work behind a button had to say.
 *
 * An action, a page or any endpoint built with
 * `generic.tasks.operation_response` answers with
 *
 *   {message, level, operation: {id, label, finished, level, summary,
 *                                report, counts, error, url}}
 *
 * and this file draws it: a card in the toast region holding a tree of
 * levelled lines, sections folded unless something in them went wrong.
 * An operation still running elsewhere (a worker, a thread) shows as
 * running, and the same card turns into its report when the
 * `operation.finished` event for that run reaches the page.
 *
 *   Generic.operations.post(url, body)     // send, then draw the answer
 *   Generic.operations.handle(answer)      // draw an answer already had
 *                                          // ({redirect: "/path/"} opens it)
 *
 * Every value reaches the page through textContent: a report line is
 * text, never HTML, and a link is followed only when isSafeUrl agrees.
 *
 * Non-ASCII characters are written as \uXXXX escapes.
 */
(function (window, document) {
  "use strict";

  var Generic = (window.Generic = window.Generic || {});
  var t = Generic.t;

  var LEVELS = ["info", "success", "warning", "error"];
  var ICONS = {
    info: "info",
    success: "check_circle",
    warning: "warning",
    error: "error"
  };

  //: Cards by run id, while the page still has them.
  var cards = {};

  function el(tag, className, text) {
    var node = document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (text !== undefined && text !== null && text !== "") {
      node.textContent = String(text);
    }

    return node;
  }

  function icon(name, extra) {
    var node = el(
      "span",
      "icon material-symbols-outlined" + (extra ? " " + extra : ""),
      name
    );

    node.setAttribute("aria-hidden", "true");

    return node;
  }

  function level(value) {
    return LEVELS.indexOf(value) === -1 ? "info" : value;
  }

  function worst(values) {
    var found = 0;

    values.forEach(function (value) {
      found = Math.max(found, LEVELS.indexOf(level(value)));
    });

    return LEVELS[found];
  }

  /** A node's level, or its children's worst when it is worse. */
  function nodeLevel(node) {
    var children = node.children || [];

    return worst([node.level].concat(children.map(nodeLevel)));
  }

  function countLines(nodes, counts) {
    (nodes || []).forEach(function (node) {
      if ((node.children || []).length) {
        countLines(node.children, counts);
      } else {
        var key = level(node.level);
        counts[key] = (counts[key] || 0) + 1;
      }
    });

    return counts;
  }

  /** "2 errors, 1 warning": what a closed section still says. */
  function describeCounts(counts) {
    var parts = [];

    if (counts.error) {
      parts.push(
        Generic.format(Generic.nt("%(count)s error", "%(count)s errors", counts.error), {
          count: counts.error
        })
      );
    }

    if (counts.warning) {
      parts.push(
        Generic.format(
          Generic.nt("%(count)s warning", "%(count)s warnings", counts.warning),
          { count: counts.warning }
        )
      );
    }

    return parts.join(", ");
  }

  /* -- The tree ---------------------------------------------------------- */

  function line(node) {
    var nodeLevelName = nodeLevel(node);
    var head = el("span", "report__line");
    var title;

    head.appendChild(icon(ICONS[nodeLevelName], "icon--sm report__icon"));

    if (node.url && Generic.isSafeUrl(node.url)) {
      title = el("a", "report__title", node.title);
      title.href = node.url;
    } else {
      title = el("span", "report__title", node.title);
    }

    head.appendChild(title);

    return head;
  }

  /**
   * Nodes as nested lists. A section is a <details>: open when
   * something in it needs reading, closed - with its counts on the
   * title - when everything in it went well.
   */
  function tree(nodes, depth) {
    var list = el("ul", "report" + (depth ? " report--nested" : ""));

    (nodes || []).forEach(function (node) {
      var nodeLevelName = nodeLevel(node);
      var item = el("li", "report__item report__item--" + nodeLevelName);
      var children = node.children || [];

      if (children.length) {
        var details = el("details", "report__section");
        var summary = el("summary", "report__summary");
        var counts = describeCounts(countLines(children, {}));

        summary.appendChild(line(node));

        if (counts) {
          summary.appendChild(el("span", "report__counts", counts));
        }

        details.appendChild(summary);

        if (node.detail) {
          details.appendChild(el("p", "report__detail", node.detail));
        }

        details.appendChild(tree(children, depth + 1));
        details.open =
          nodeLevelName === "warning" || nodeLevelName === "error";
        item.appendChild(details);
      } else {
        item.appendChild(line(node));

        if (node.detail) {
          item.appendChild(el("p", "report__detail", node.detail));
        }
      }

      list.appendChild(item);
    });

    return list;
  }

  /* -- The card ----------------------------------------------------------- */

  function region() {
    var node = document.getElementById("toasts");

    if (!node) {
      node = el("div", "toasts");
      node.id = "toasts";
      node.setAttribute("aria-live", "polite");
      document.body.appendChild(node);
    }

    return node;
  }

  function fill(card, answer) {
    var operation = answer.operation || {};
    var finished = operation.finished !== false;
    var cardLevel = finished
      ? level(operation.level || answer.level)
      : "info";
    var body = el("div", "toast__text operation__body");
    var close = card.querySelector(".operation__close");

    card.className = "toast toast--" + cardLevel + " operation";
    card.setAttribute("role", cardLevel === "error" ? "alert" : "status");
    card.setAttribute("aria-busy", finished ? "false" : "true");
    card.textContent = "";

    card.appendChild(
      finished ? icon(ICONS[cardLevel]) : el("span", "spinner operation__spinner")
    );

    if (operation.label && operation.label !== answer.message) {
      body.appendChild(el("strong", "operation__title", operation.label));
    }

    body.appendChild(
      el("div", "operation__message", answer.message || operation.summary || t("Done."))
    );

    if (operation.error) {
      body.appendChild(el("pre", "operation__error", operation.error));
    }

    if ((operation.report || []).length) {
      body.appendChild(tree(operation.report, 0));
    }

    if (operation.url && Generic.isSafeUrl(operation.url)) {
      var link = el(
        "a",
        "operation__link",
        finished ? t("Open the report") : t("Follow it on its page")
      );

      link.href = operation.url;
      body.appendChild(link);
    }

    card.appendChild(body);
    card.appendChild(close);

    window.clearTimeout(card.dismissTimer);

    // A clean success may go by itself; anything to read stays until
    // it is closed.
    var counts = operation.counts || {};

    if (finished && (cardLevel === "success" || cardLevel === "info") &&
        !counts.warning && !counts.error) {
      card.dismissTimer = window.setTimeout(function () {
        dismiss(card);
      }, 8000);
    }

    card.operation = operation;
  }

  function dismiss(card) {
    window.clearTimeout(card.dismissTimer);

    if (card.operation && cards[card.operation.id] === card) {
      delete cards[card.operation.id];
    }

    card.remove();
  }

  /** Draw an answer: a new card, or the card of a run already shown. */
  function show(answer) {
    var operation = answer.operation || {};
    var card = operation.id !== null && operation.id !== undefined
      ? cards[operation.id]
      : null;

    if (!card) {
      card = el("div", "toast operation");

      var close = el("button", "icon-button icon-button--sm operation__close");

      close.type = "button";
      close.setAttribute("aria-label", t("Dismiss"));
      close.appendChild(icon("close", "icon--sm"));
      close.addEventListener("click", function () {
        dismiss(card);
      });
      card.appendChild(close);
      region().appendChild(card);

      if (operation.id !== null && operation.id !== undefined) {
        cards[operation.id] = card;
      }
    }

    fill(card, answer);

    return card;
  }

  function isLocalPath(value) {
    return typeof value === "string" && /^\/(?![\/\\])/.test(value);
  }

  /**
   * Whatever an endpoint answered: an operation is drawn as one, any
   * other answer as the toast its message and level make.
   */
  function handle(answer) {
    // A page of this site to open next: an action that opens a form
    // with the selection filled in. Only a path, never another site.
    if (answer && isLocalPath(answer.redirect)) {
      window.location.assign(answer.redirect);

      return answer;
    }

    if (answer && answer.operation) {
      show(answer);
    } else if (answer && answer.message) {
      Generic.toast(answer.message, answer.level || "success");
    } else {
      Generic.toast(t("Done."), "success");
    }

    return answer;
  }

  /** POST, then draw the answer; an error answer is a toast. */
  function post(url, body) {
    return Generic.api.post(url, body || {}).then(handle, function (error) {
      var detail = error && error.data && error.data.detail;

      Generic.toast(detail || (error && error.message) || t("Something went wrong."), "error");

      throw error;
    });
  }

  /**
   * Whether a card on this page already speaks for a notification:
   * the bell then leaves its toast out rather than saying it twice.
   */
  function claims(url) {
    return Boolean(url) && Object.keys(cards).some(function (id) {
      return cards[id].operation && cards[id].operation.url === url;
    });
  }

  function finished(payload) {
    if (payload && cards[payload.id]) {
      show({
        message: payload.summary || payload.label,
        level: payload.level,
        operation: payload
      });
    }
  }

  Generic.ready(function () {
    if (Generic.events && typeof Generic.events.on === "function") {
      Generic.events.on("operation.finished", finished);
    }
  });

  Generic.operations = {
    claims: claims,
    handle: handle,
    post: post,
    show: show,
    tree: tree
  };
})(window, document);

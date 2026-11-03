/**
 * The note editor's clipboard: lines read from what was copied, and
 * lines written for whatever they are pasted into.
 *
 *   Generic.noteClipboard.read(clipboardData)  -> [{kind, indent, text, done}]
 *   Generic.noteClipboard.fromHtml(html)       -> the same, from HTML
 *   Generic.noteClipboard.fromText(text)       -> the same, from plain text
 *   Generic.noteClipboard.write(lines)         -> {text, html}
 *
 * OneNote, Word, Outlook and the browsers put HTML on the clipboard
 * beside the plain text, and the HTML is what still knows the lists,
 * their depth, the headings, the to-dos and the tables: it is read
 * first, in a document of its own (DOMParser: nothing in it runs or
 * loads), only for its text. Plain text is read for its markers: tabs,
 * bullets (the glyphs OneNote and Word write too), [ ], # and numbers.
 *
 * What is written back is HTML of plain lists, headings and paragraphs
 * - each element saying its line's kind and indent, so a paste into a
 * note comes back exactly - and plain text with the same markers.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic || (window.Generic = {});

  var MAX_INDENT = 4;

  //: Nothing to read in these.
  var SKIPPED = /^(SCRIPT|STYLE|HEAD|TITLE|META|LINK|TEMPLATE|NOSCRIPT|OBJECT|IFRAME|SVG|CANVAS|VIDEO|AUDIO|SELECT|BUTTON|XML)$/;

  //: A line of its own each.
  var BLOCKS = /^(P|DIV|BLOCKQUOTE|SECTION|ARTICLE|HEADER|FOOTER|MAIN|NAV|ASIDE|ADDRESS|FIGURE|FIGCAPTION|DL|DT|DD|CENTER|FORM|FIELDSET|LEGEND|DETAILS|SUMMARY)$/;

  //: Bullets as text: OneNote and Word write them so in plain text.
  var BULLET = /^[\u2022\u25e6\u25aa\u25ab\u25cf\u25cb\u2023\u2043\u00b7\u25a0\u2013\u2014\u27a2\u2794\u25ba\u2192*-]\s+/;
  //: Word's second and third levels: "o" and the Wingdings square, then a tab.
  var BULLET_TAB = /^[o\u00a7\u00d8\uf0a7\uf0b7\uf076\uf0d8]\t/;
  var UNCHECKED = /^(\[\s?\]|[\u2610\u25a1\u274f])\s*/;
  var CHECKED = /^(\[[xX\u2713\u2714]\]|[\u2611\u2612\u2713\u2714\u2705])\s*/;
  var HEADING = /^#{1,6}\s+/;
  var TO_DO = /(^|[\s:_-])(to[\s-]?do|t[a\u00e2]che|checkbox|case [a\u00e0] cocher)/i;
  var DONE = /(complete|completed|done|checked|termin)/i;
  var INVISIBLE = /[\u200b-\u200d\u2060\ufeff\u00ad]/g;

  function clean(text) {
    return String(text || "")
      .replace(INVISIBLE, "")
      .replace(/[\u00a0\u2007\u202f]/g, " ");
  }

  function squeeze(text) {
    return clean(text).replace(/[ \t\n\r\f\v]+/g, " ");
  }

  function clamp(indent) {
    return Math.min(Math.max(indent || 0, 0), MAX_INDENT);
  }

  /** A line's markers, written as text: the kind they say. A bullet
   * may still say it is a to-do. */
  function markers(line) {
    var text = line.text;
    var match;

    if (line.kind === "bullet" && (match = CHECKED.exec(text) || UNCHECKED.exec(text))) {
      line.kind = "check";
      line.done = CHECKED.test(text);
      line.text = text.slice(match[0].length);

      return line;
    }

    if (line.kind !== "text") {
      return line;
    }

    if ((match = CHECKED.exec(text))) {
      line.kind = "check";
      line.done = true;
    } else if ((match = UNCHECKED.exec(text))) {
      line.kind = "check";
    } else if ((match = BULLET_TAB.exec(text) || BULLET.exec(text))) {
      line.kind = "bullet";
    } else if ((match = HEADING.exec(text))) {
      line.kind = "heading";
    }

    if (match) {
      line.text = text.slice(match[0].length);
    }

    return line;
  }

  /** Empty lines at either end dropped; those between kept, as many
   * as there were. */
  function tidy(lines) {
    var out = [];

    lines.forEach(function (line) {
      line.text = line.text.replace(/\s+$/, "");

      if (line.kind !== "text" || line.text || out.length) {
        out.push(line);
      }
    });

    while (out.length && out[out.length - 1].kind === "text" && !out[out.length - 1].text) {
      out.pop();
    }

    // The shallowest line sits where the paste starts.
    var least = out.reduce(function (low, line) {
      return Math.min(low, line.indent);
    }, MAX_INDENT);

    out.forEach(function (line) {
      line.indent = clamp(line.indent - least);
    });

    return out;
  }

  /* -- Plain text ---------------------------------------------------------- */

  function fromText(text) {
    var rows = clean(text).replace(/\r\n?/g, "\n").replace(/\u2028|\u2029/g, "\n").split("\n");

    return tidy(
      rows.map(function (row) {
        var lead = /^[\t ]*/.exec(row)[0];
        var tabs = (lead.match(/\t/g) || []).length;
        var spaces = lead.length - tabs;

        var line = markers({
          kind: "text",
          indent: clamp(tabs + Math.floor(spaces / 4)),
          text: row.slice(lead.length),
          done: false
        });

        line.text = line.text.replace(/\t+/g, " ").replace(/ {2,}/g, " ");

        return line;
      })
    );
  }

  /* -- HTML ------------------------------------------------------------------ */

  /** A CSS length in pixels, roughly: 0 when it cannot be read. */
  function pixels(value, unit) {
    var number = parseFloat(value) || 0;
    var per = { px: 1, pt: 4 / 3, in: 96, cm: 37.8, mm: 3.78, em: 16, rem: 16 };

    return number * (per[unit] || 0);
  }

  function styleOf(element) {
    return (element.getAttribute && element.getAttribute("style")) || "";
  }

  function marginIndent(element) {
    var match = /margin-left\s*:\s*(-?[\d.]+)\s*(px|pt|in|cm|mm|em|rem)/i.exec(styleOf(element));

    if (!match) {
      return 0;
    }

    return Math.max(Math.round(pixels(match[1], match[2].toLowerCase()) / 36), 0);
  }

  /** A font size in points, from an inline style: 0 when none. */
  function points(element) {
    var match = element && /font-size\s*:\s*([\d.]+)\s*(pt|px)/i.exec(styleOf(element));

    if (!match) {
      return 0;
    }

    return parseFloat(match[1]) * (match[2].toLowerCase() === "px" ? 0.75 : 1);
  }

  /** OneNote writes its headings as paragraphs in a larger type (16 pt
   * against 11): a short one, in 13.5 pt or more, is a heading. */
  function looksLikeHeading(element) {
    var only = element.children.length === 1 ? element.children[0] : null;
    var size = Math.max(points(element), only && !BLOCKS.test(only.tagName) ? points(only) : 0);
    var text = squeeze(element.textContent).trim();

    if (/\bMso(Title|Subtitle|Heading\d)\b/.test(element.className || "")) {
      return !!text;
    }

    return size >= 13.5 && text.length > 0 && text.length <= 120;
  }

  function hidden(element) {
    var style = styleOf(element);

    return /display\s*:\s*none/i.test(style) || /mso-list\s*:\s*ignore/i.test(style) || element.hidden;
  }

  function tagged(element) {
    var tag = (element.getAttribute("data-tag") || "") + " " + (element.getAttribute("data-type") || "");

    if (!TO_DO.test(tag)) {
      return null;
    }

    return { done: DONE.test(tag) };
  }

  function Reader() {
    this.lines = [];
    this.current = null;
  }

  Reader.prototype.flush = function () {
    if (this.current) {
      this.lines.push(this.current);
      this.current = null;
    }
  };

  Reader.prototype.open = function (context) {
    this.flush();
    this.current = {
      kind: context.kind || "text",
      indent: context.indent || 0,
      text: "",
      done: !!context.done,
      exact: !!context.exact
    };

    if (context.prefix) {
      this.current.text = context.prefix;
      context.prefix = "";
    }

    return this.current;
  };

  Reader.prototype.add = function (text, context) {
    if (!text) {
      return;
    }

    if (!this.current) {
      // Blank space between blocks is not a line.
      if (!text.trim()) {
        return;
      }

      this.open(context);
    }

    this.current.text += text;
  };

  /** A to-do box (an image, a check box, a tag) met in the line. */
  Reader.prototype.box = function (done, context) {
    if (!this.current) {
      this.open(context);
    }

    if (!this.current.text.trim() && !this.current.exact) {
      this.current.kind = "check";
      this.current.done = done;
    }
  };

  /** A block's own context: its kind, indent, and whether a line is
   * written exactly as an editor wrote it (data-line-kind). */
  Reader.prototype.blockContext = function (element, context) {
    var next = {
      kind: "text",
      indent: context.indent,
      depth: context.depth,
      ordered: context.ordered,
      pre: context.pre
    };
    var exact = element.getAttribute("data-line-kind");
    var word = /mso-list\s*:\s*\w+\s+level(\d+)/i.exec(styleOf(element));
    var tag = tagged(element);

    if (exact) {
      next.kind = exact === "task" ? "text" : exact;
      next.indent = parseInt(element.getAttribute("data-line-indent") || "0", 10) || 0;
      next.done = element.getAttribute("data-line-done") === "true";
      next.exact = true;

      return next;
    }

    if (word) {
      next.kind = "bullet";
      next.indent = context.indent + parseInt(word[1], 10) - 1;
    } else {
      next.indent = context.indent + marginIndent(element);
    }

    if (tag) {
      next.kind = "check";
      next.done = tag.done;
    } else if (!word && /^(P|DIV)$/i.test(element.tagName) && looksLikeHeading(element)) {
      next.kind = "heading";
    }

    return next;
  };

  Reader.prototype.walk = function (node, context) {
    var self = this;

    if (node.nodeType === 3) {
      if (context.pre) {
        clean(node.data)
          .replace(/\r\n?/g, "\n")
          .split("\n")
          .forEach(function (part, index) {
            if (index) {
              self.open(context);
            }

            self.add(part, context);
          });
      } else {
        this.add(squeeze(node.data), context);
      }

      return;
    }

    if (node.nodeType !== 1) {
      return;
    }

    var element = node;
    var tag = element.tagName.toUpperCase();

    if (SKIPPED.test(tag) || /^(V|W|M):/.test(tag) || hidden(element)) {
      return;
    }

    if (tag === "BR") {
      if (this.current) {
        this.open({ kind: "text", indent: this.current.indent });
      } else {
        this.open({ kind: "text", indent: context.indent });
      }

      return;
    }

    if (tag === "IMG") {
      var alt = (element.getAttribute("alt") || "") + " " + (element.getAttribute("title") || "");

      if (TO_DO.test(alt)) {
        this.box(DONE.test(alt), context);
      }

      return;
    }

    if (tag === "INPUT") {
      if ((element.getAttribute("type") || "").toLowerCase() === "checkbox") {
        this.box(element.hasAttribute("checked"), context);
      }

      return;
    }

    if (tag === "HR") {
      this.flush();
      return;
    }

    if (tag === "UL" || tag === "OL") {
      var list = {
        kind: context.kind,
        indent: context.indent + marginIndent(element),
        depth: (context.depth || 0) + 1,
        ordered: tag === "OL",
        counter: parseInt(element.getAttribute("start") || "1", 10) || 1,
        pre: context.pre
      };

      this.flush();
      this.children(element, list);
      this.flush();

      return;
    }

    if (tag === "LI") {
      var item = this.blockContext(element, context);

      if (!item.exact) {
        item.kind = item.kind === "check" ? "check" : context.ordered ? "text" : "bullet";
        item.indent = context.indent + Math.max((context.depth || 1) - 1, 0);

        if (context.ordered) {
          var number = parseInt(element.getAttribute("value") || "", 10) || context.counter || 1;

          item.prefix = number + ". ";
          context.counter = number + 1;
        }
      }

      // A list inside the item sits a level deeper (its depth says so).
      this.open(item);
      this.children(element, {
        kind: item.kind,
        indent: context.indent,
        depth: context.depth,
        ordered: context.ordered,
        exact: item.exact,
        done: item.done,
        prefix: "",
        pre: context.pre
      });
      this.flush();

      return;
    }

    if (/^H[1-6]$/.test(tag)) {
      var heading = this.blockContext(element, context);

      if (!heading.exact) {
        heading.kind = "heading";
      }

      this.open(heading);
      this.children(element, heading);
      this.flush();

      return;
    }

    if (tag === "TR") {
      var cells = [];

      Array.prototype.forEach.call(element.children, function (cell) {
        if (/^T[DH]$/i.test(cell.tagName)) {
          var inner = new Reader();

          inner.children(cell, { kind: "text", indent: 0, depth: 0 });
          inner.flush();
          cells.push(
            inner.lines
              .map(function (line) {
                return line.text.trim();
              })
              .filter(Boolean)
              .join(" / ")
          );
        }
      });

      if (cells.some(Boolean)) {
        this.open({ kind: "text", indent: context.indent });
        this.current.text = cells.join(" | ");
        this.flush();
      }

      return;
    }

    if (tag === "PRE") {
      var pre = this.blockContext(element, context);

      pre.pre = true;
      this.flush();
      this.open(pre);
      this.children(element, pre);
      this.flush();

      return;
    }

    if (BLOCKS.test(tag)) {
      var block = this.blockContext(element, context);
      var count = this.lines.length;

      this.flush();
      this.children(element, block);
      this.flush();

      // An empty paragraph is OneNote's and Word's blank line.
      if (tag === "P" && this.lines.length === count) {
        this.lines.push({ kind: "text", indent: block.indent, text: "", done: false });
      }

      return;
    }

    // Inline: its text, and a link's address when the text is not it.
    this.children(element, context);

    if (tag === "A") {
      var href = element.getAttribute("href") || "";
      var text = squeeze(element.textContent).trim();

      if (/^https?:\/\//i.test(href) && text && text !== href && this.current) {
        this.current.text += " (" + href + ")";
      }
    }
  };

  Reader.prototype.children = function (element, context) {
    var child = element.firstChild;

    while (child) {
      this.walk(child, context);
      child = child.nextSibling;
    }
  };

  function fromHtml(html) {
    if (!html || !window.DOMParser) {
      return [];
    }

    // Word's and OneNote's conditional comments hold the list markers
    // twice over; the comments go, and what they wrap with them.
    var source = String(html)
      .replace(/<!--\[if[\s\S]*?<!\[endif\]-->/gi, "")
      .replace(/<!\[if[^\]]*\]>[\s\S]*?<!\[endif\]>/gi, "");
    var parsed = new window.DOMParser().parseFromString(source, "text/html");
    var reader = new Reader();

    if (!parsed || !parsed.body) {
      return [];
    }

    reader.children(parsed.body, { kind: "text", indent: 0, depth: 0 });
    reader.flush();

    return tidy(
      reader.lines.map(function (line) {
        var exact = line.exact;

        line.text = line.text.replace(/ {2,}/g, " ").replace(/^ /, "");
        delete line.exact;

        return exact ? line : markers(line);
      })
    );
  }

  /** What was copied, as lines: its HTML when it has some, its text
   * otherwise. */
  function read(data) {
    if (!data) {
      return [];
    }

    var html = data.getData("text/html");
    var text = data.getData("text/plain");
    var lines = html ? fromHtml(html) : [];

    // An HTML wrapper with nothing in it (some apps put one around an
    // image): the text says more.
    if (!lines.length || (text && !lines.some(function (line) {
      return line.text;
    }))) {
      lines = fromText(text || "");
    }

    return lines;
  }

  /* -- Writing ------------------------------------------------------------- */

  var BOX = "\u2610 ";
  var TICKED = "\u2611 ";

  function prefix(line) {
    if (line.kind === "heading") {
      return "# ";
    }

    if (line.kind === "bullet") {
      return "- ";
    }

    if (line.kind === "check") {
      return line.done ? "[x] " : "[ ] ";
    }

    if (line.kind === "task" && line.reference) {
      return line.reference + " ";
    }

    return "";
  }

  /** Plain text: a tab (or `options.indent`) per level, markers. */
  function toText(lines, options) {
    var step = (options && options.indent) || "\t";

    return lines
      .map(function (line) {
        return new Array(line.indent + 1).join(step) + prefix(line) + line.text;
      })
      .join("\n");
  }

  function mark(element, line) {
    element.setAttribute("data-line-kind", line.kind);
    element.setAttribute("data-line-indent", String(line.indent));

    if (line.kind === "check") {
      element.setAttribute("data-line-done", line.done ? "true" : "false");
    }

    return element;
  }

  function toHtml(lines) {
    var root = document.createElement("div");
    var stack = [];

    lines.forEach(function (line) {
      var listed = line.kind === "bullet" || line.kind === "check";

      if (!listed) {
        stack = [];

        var block = document.createElement(line.kind === "heading" ? "h2" : "p");

        if (line.indent) {
          block.style.marginLeft = line.indent * 36 + "px";
        }

        if (line.kind === "task" && line.reference) {
          var strong = document.createElement("strong");

          strong.textContent = line.reference;
          block.appendChild(strong);
          block.appendChild(document.createTextNode(" "));
        }

        block.appendChild(document.createTextNode(line.text));
        root.appendChild(mark(block, line));

        return;
      }

      while (stack.length && stack[stack.length - 1].indent > line.indent) {
        stack.pop();
      }

      if (!stack.length || stack[stack.length - 1].indent < line.indent) {
        var list = document.createElement("ul");
        var parent = stack.length ? stack[stack.length - 1].list.lastElementChild || stack[stack.length - 1].list : root;

        if (!stack.length && line.indent) {
          list.style.marginLeft = line.indent * 36 + "px";
        }

        parent.appendChild(list);
        stack.push({ indent: line.indent, list: list });
      }

      var item = document.createElement("li");

      if (line.kind === "check") {
        item.style.listStyleType = "none";
        item.appendChild(document.createTextNode(line.done ? TICKED : BOX));
      }

      item.appendChild(document.createTextNode(line.text));
      stack[stack.length - 1].list.appendChild(mark(item, line));
    });

    return root.innerHTML;
  }

  function write(lines) {
    return { text: toText(lines), html: toHtml(lines) };
  }

  Generic.noteClipboard = {
    read: read,
    fromHtml: fromHtml,
    fromText: fromText,
    toText: toText,
    toHtml: toHtml,
    write: write
  };
})(window, document);

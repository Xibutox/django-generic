/**
 * The note editor: a note written line by line.
 *
 * Each line is a kind - text, heading, bullet, to-do, or task - and a
 * task line is a task: saved once, it is numbered (FNC-0007, DM-0003),
 * shows its status, the time spent on it, and a button starting or
 * stopping the timer. Typing at the start of a line changes its kind:
 * "# " a heading, "- " a bullet, "[] " a to-do, "/fnc ", "/dm " or "/aut " a
 * task; the buttons above the lines add a line of any kind. Enter starts
 * a line, Backspace on an empty one removes it, Tab and Shift+Tab
 * indent.
 *
 * Lines move: by their handle (drag), or Alt+Shift+Up/Down - a line
 * takes the lines indented under it along. Shift+Up/Down past a line's
 * edge, a click on a handle or Ctrl+A twice select whole lines, to copy,
 * cut, delete, indent, move or attach to a task; Escape lets go. What is
 * copied is HTML and plain text both, and a paste reads either - lists,
 * headings and to-dos from OneNote or Word included - through
 * note-clipboard.js. A paste, a move or a deletion can be undone (the
 * toast's Undo, or Ctrl+Z right after).
 *
 * The note saves itself a moment after the last change (Ctrl+S at
 * once): the whole note is posted to its document page
 * (planner/documents.py), which answers what it stored.
 *
 *   <section class="note-editor" data-url="<the note's document page>"
 *            data-attach-url="<the note's attach page>">
 *
 * Text reaches the page through textContent and form values, addresses
 * through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var clipboard = Generic.noteClipboard;

  var KINDS = [
    { kind: "text", icon: "notes", label: t("Text"), short: t("Text") },
    { kind: "heading", icon: "title", label: t("Heading"), short: t("Heading") },
    { kind: "bullet", icon: "format_list_bulleted", label: t("Bullet"), short: t("Bullet") },
    { kind: "check", icon: "check_box", label: t("To-do"), short: t("To-do") },
    { kind: "task", taskKind: "FNC", icon: "bug_report", label: t("FNC task - a ticket"), short: "FNC" },
    { kind: "task", taskKind: "DM", icon: "rocket_launch", label: t("DM task - an evolution"), short: "DM" },
    { kind: "task", taskKind: "AUT", icon: "groups", label: t("AUT task - a meeting, support"), short: "AUT" }
  ];

  //: What a line may start with to change its kind.
  var SHORTCUTS = [
    { pattern: /^#\s/, kind: "heading" },
    { pattern: /^[-*]\s/, kind: "bullet" },
    { pattern: /^\[\s?\]\s/, kind: "check" },
    { pattern: /^\[x\]\s/i, kind: "check", done: true },
    { pattern: /^\/fnc\s/i, kind: "task", taskKind: "FNC" },
    { pattern: /^\/dm\s/i, kind: "task", taskKind: "DM" },
    { pattern: /^\/(aut|autre|autres|other)\s/i, kind: "task", taskKind: "AUT" }
  ];

  //: The keys, for the list the keyboard button opens.
  var KEYS = [
    ["Enter", t("A new line; Shift+Enter breaks the line inside it")],
    ["Tab / Shift+Tab", t("Indent, outdent")],
    ["Alt+Shift+\u2191 / \u2193", t("Move the line, with the lines indented under it (Ctrl+Shift+\u2191 / \u2193 too)")],
    ["Shift+\u2191 / \u2193", t("At the start or end of a line: select whole lines")],
    ["Ctrl+A", t("Twice: select every line")],
    ["Ctrl+C / Ctrl+X / Ctrl+V", t("Copy, cut, paste lines - from OneNote, Word, Outlook too")],
    ["Delete", t("Remove the selected lines")],
    ["Ctrl+Z", t("Undo a paste, a move, a removal")],
    ["Ctrl+Enter", t("Tick or untick a to-do")],
    ["Ctrl+S", t("Save now")],
    ["Escape", t("Let go of the selection")]
  ];

  var SAVE_DELAY = 900;
  var MAX_INDENT = 4;
  var UNDO_DEPTH = 50;
  var counter = 0;

  function el(tag, className, text) {
    var node = document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }

    return node;
  }

  function icon(name) {
    var node = el("span", "icon material-symbols-outlined icon--sm", name);

    node.setAttribute("aria-hidden", "true");

    return node;
  }

  function iconButton(name, label, className) {
    var node = el("button", "icon-button icon-button--sm " + (className || ""));

    node.type = "button";
    node.title = label;
    node.setAttribute("aria-label", label);
    node.appendChild(icon(name));

    return node;
  }

  function key() {
    counter += 1;

    return "line-" + counter;
  }

  function kindOf(line) {
    for (var index = 0; index < KINDS.length; index += 1) {
      var entry = KINDS[index];

      if (entry.kind === line.kind && (!entry.taskKind || entry.taskKind === line.taskKind)) {
        return entry;
      }
    }

    return KINDS[0];
  }

  function hours(text) {
    var value = parseFloat(text || "0") || 0;
    var whole = Math.floor(value);
    var minutes = Math.round((value - whole) * 60);

    if (!whole && !minutes) {
      return "0 h";
    }

    return whole + " h" + (minutes ? " " + (minutes < 10 ? "0" : "") + minutes : "");
  }

  function clampIndent(indent) {
    return Math.min(Math.max(indent || 0, 0), MAX_INDENT);
  }

  function command(event) {
    return event.ctrlKey || event.metaKey;
  }

  /** Alt+Shift+Up/Down (OneNote's), or Ctrl+Shift+Up/Down: a move. */
  function moveStep(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
      return 0;
    }

    if (!event.shiftKey || !(event.altKey || command(event))) {
      return 0;
    }

    return event.key === "ArrowUp" ? -1 : 1;
  }

  /* -- The editor ------------------------------------------------------ */

  function NoteEditor(element) {
    this.element = element;
    this.url = element.getAttribute("data-url");
    this.attachUrl = element.getAttribute("data-attach-url");
    this.lines = [];
    this.timer = null;
    this.saving = null;
    this.dirty = false;
    this.again = false;
    this.selection = null;
    this.current = null;
    this.history = [];
    this.undoReady = false;
    this.dragging = null;
    this.copying = null;
  }

  NoteEditor.prototype.start = function () {
    var self = this;

    Generic.api
      .get(this.url)
      .then(function (answer) {
        self.load(answer);
        self.build();
      })
      .catch(function (error) {
        self.element.textContent = "";
        self.element.appendChild(el("p", "callout callout--danger", (error && error.message) || t("The note could not be loaded.")));
      });

    window.addEventListener("beforeunload", function (event) {
      if (self.dirty || self.saving) {
        event.preventDefault();
        event.returnValue = "";
      }
    });

    // Copying, cutting and pasting whole lines: the selection has the
    // focus (the list), or a toolbar button asked for it.
    document.addEventListener("copy", function (event) {
      self.copied(event, false);
    });
    document.addEventListener("cut", function (event) {
      self.copied(event, true);
    });
    document.addEventListener("paste", function (event) {
      if (self.selection && document.activeElement === self.list) {
        self.pasteOverSelection(event);
      }
    });
  };

  NoteEditor.prototype.load = function (answer) {
    this.canEdit = !!answer.canEdit;
    this.canAddTasks = !!answer.canAddTasks;
    this.canTime = !!answer.canTime;
    this.canAttach = !!answer.canAttach && !!this.attachUrl;
    this.statuses = answer.statuses || [];
    this.criticalities = answer.criticalities || [];
    this.title = answer.title || "";
    this.lines = (answer.lines || []).map(function (line) {
      return {
        key: key(),
        id: line.id,
        kind: line.kind,
        indent: line.indent || 0,
        text: line.text || "",
        done: !!line.done,
        task: line.task,
        taskKind: line.task ? line.task.kind : "FNC"
      };
    });

    if (!this.lines.length) {
      this.lines.push(this.blank());
    }
  };

  NoteEditor.prototype.blank = function (kind, indent, taskKind) {
    return {
      key: key(),
      id: null,
      kind: kind || "text",
      indent: indent || 0,
      text: "",
      done: false,
      task: null,
      taskKind: taskKind || "FNC"
    };
  };

  NoteEditor.prototype.build = function () {
    var self = this;
    var head = el("div", "note-editor__head");

    this.element.textContent = "";
    this.titleInput = el("input", "note-editor__title");
    this.titleInput.value = this.title;
    this.titleInput.setAttribute("aria-label", t("Title"));
    this.titleInput.readOnly = !this.canEdit;
    this.titleInput.addEventListener("input", function () {
      self.changed();
    });
    this.titleInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === "ArrowDown") {
        event.preventDefault();
        self.focus(self.lines[0], 0);
      }
    });

    this.status = el("span", "note-editor__status muted");
    this.status.setAttribute("aria-live", "polite");
    head.appendChild(this.titleInput);
    head.appendChild(this.status);
    this.element.appendChild(head);
    this.element.appendChild(this.toolbar());

    this.keys = this.keyList();
    this.element.appendChild(this.keys);

    this.list = el("div", "note-editor__lines");
    this.list.setAttribute("role", "list");
    this.list.setAttribute("aria-label", t("Lines"));
    this.list.tabIndex = -1;
    this.list.addEventListener("keydown", function (event) {
      if (event.target === self.list) {
        self.selectionKey(event);
      }
    });
    this.list.addEventListener("focusin", function (event) {
      if (event.target !== self.list && event.target.classList.contains("note-line__text")) {
        self.clearSelection();
      }
    });
    this.dragAndDrop();
    this.element.appendChild(this.list);

    if (this.canEdit) {
      this.element.appendChild(
        el(
          "p",
          "note-editor__help muted",
          t("Start a line with # for a heading, - for a bullet, [] for a to-do, /fnc, /dm or /aut for a task. Tab indents.")
        )
      );
    }

    this.lines.forEach(function (line) {
      self.list.appendChild(self.row(line));
    });
    this.lines.forEach(function (line) {
      self.grow(line);
    });
    this.showStatus(t("Saved"));
  };

  /* -- The toolbar ----------------------------------------------------- */

  NoteEditor.prototype.toolbar = function () {
    var self = this;
    var bar = el("div", "note-editor__toolbar");

    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", t("Note tools"));

    if (this.canEdit) {
      var add = el("div", "note-editor__tools");

      add.appendChild(el("span", "note-editor__tools-label muted", t("Add")));
      KINDS.forEach(function (entry) {
        if (entry.kind === "task" && !self.canAddTasks) {
          return;
        }

        var button = el("button", "button button--sm button--ghost note-editor__add note-editor__add--" + (entry.taskKind || entry.kind).toLowerCase());

        button.type = "button";
        button.title = Generic.format(t("Add a line: %(kind)s"), { kind: entry.label });
        button.appendChild(icon(entry.icon));
        button.appendChild(el("span", "", entry.short));
        // The line being written keeps the focus until the click.
        button.addEventListener("mousedown", function (event) {
          event.preventDefault();
        });
        button.addEventListener("click", function () {
          self.addLine(entry.kind, entry.taskKind);
        });
        add.appendChild(button);
      });
      bar.appendChild(add);
    }

    var actions = el("div", "note-editor__tools note-editor__tools--end");
    var copy = iconButton("content_copy", t("Copy the selected lines, or the whole note"));

    copy.addEventListener("mousedown", function (event) {
      event.preventDefault();
    });
    copy.addEventListener("click", function () {
      self.copyLines(self.selection ? self.selectedLines() : self.lines.slice());
    });
    actions.appendChild(copy);

    if (this.canAttach) {
      var attach = iconButton("attach_file", t("Attach the selected lines, or the current one, to a task"));

      attach.addEventListener("mousedown", function (event) {
        event.preventDefault();
      });
      attach.addEventListener("click", function () {
        self.attach(self.selection ? self.selectedLines() : self.current ? [self.current] : []);
      });
      actions.appendChild(attach);
    }

    var keys = iconButton("keyboard", t("Keyboard shortcuts"));

    keys.setAttribute("aria-expanded", "false");
    keys.addEventListener("click", function () {
      var open = self.keys.hidden;

      self.keys.hidden = !open;
      keys.setAttribute("aria-expanded", open ? "true" : "false");
    });
    actions.appendChild(keys);
    bar.appendChild(actions);

    return bar;
  };

  NoteEditor.prototype.keyList = function () {
    var box = el("dl", "note-editor__keys");

    box.hidden = true;
    KEYS.forEach(function (entry) {
      var term = el("dt");

      term.appendChild(el("kbd", "", entry[0]));
      box.appendChild(term);
      box.appendChild(el("dd", "", entry[1]));
    });

    return box;
  };

  /** A line of this kind: the current line turned into it when it is
   * empty, a new one under it otherwise. */
  NoteEditor.prototype.addLine = function (kind, taskKind) {
    var line = this.current && this.lines.indexOf(this.current) !== -1 ? this.current : this.lines[this.lines.length - 1];

    if (line && !line.input.value && !line.task) {
      this.clearSelection();
      this.setKind(line, kind, taskKind);
      this.focus(line, 0);
      return;
    }

    var block = this.block(line);
    var next = this.blank(kind, line.indent, taskKind);

    this.clearSelection();
    this.insert(next, this.lines.indexOf(block[block.length - 1]) + 1);
    this.focus(next, 0);
    this.changed();
  };

  /* -- A line ------------------------------------------------------------ */

  NoteEditor.prototype.row = function (line) {
    var self = this;
    var row = el("div", "note-line");
    var handle = iconButton("drag_indicator", this.canEdit ? t("Drag to move; click to select") : t("Click to select"), "note-line__handle");
    var kind = el("button", "note-line__kind icon-button icon-button--sm");
    var text = el("textarea", "note-line__text");

    row.setAttribute("role", "listitem");
    line.row = row;
    line.input = text;

    handle.tabIndex = -1;
    handle.draggable = this.canEdit;
    handle.addEventListener("click", function (event) {
      self.handleClicked(line, event);
    });
    handle.addEventListener("dragstart", function (event) {
      self.dragStart(line, event);
    });
    handle.addEventListener("dragend", function () {
      self.dragEnd();
    });
    row.appendChild(handle);

    if (this.canEdit) {
      var add = iconButton("add", t("Add a line below"), "note-line__add");

      add.tabIndex = -1;
      add.addEventListener("click", function () {
        self.addBelow(line);
      });
      row.appendChild(add);
    }

    kind.type = "button";
    kind.disabled = !this.canEdit;
    kind.setAttribute("aria-haspopup", "menu");
    kind.addEventListener("click", function (event) {
      event.stopPropagation();
      self.menu(line, kind);
    });
    line.kindButton = kind;

    var check = el("input", "note-line__check");

    check.type = "checkbox";
    check.disabled = !this.canEdit;
    check.setAttribute("aria-label", t("Done"));
    check.addEventListener("change", function () {
      line.done = check.checked;
      self.paint(line);
      self.changed();
    });
    line.check = check;

    text.rows = 1;
    text.value = line.text;
    text.readOnly = !this.canEdit;
    text.setAttribute("aria-label", t("Line"));
    text.addEventListener("input", function () {
      self.typed(line);
    });
    text.addEventListener("keydown", function (event) {
      self.key(line, event);
    });
    text.addEventListener("paste", function (event) {
      self.paste(line, event);
    });
    text.addEventListener("focus", function () {
      self.current = line;
    });

    row.appendChild(kind);
    row.appendChild(check);
    row.appendChild(text);
    line.taskBox = el("span", "note-line__task");
    row.appendChild(line.taskBox);
    this.paint(line);

    return row;
  };

  /** Draw what the line's kind and task say. */
  NoteEditor.prototype.paint = function (line) {
    var entry = kindOf(line);
    var row = line.row;
    var selected = this.selection && this.selectedLines().indexOf(line) !== -1;

    row.className = "note-line note-line--" + line.kind + (line.done ? " is-done" : "") + (selected ? " is-selected" : "");
    row.style.setProperty("--indent", String(line.indent));
    row.setAttribute("aria-selected", selected ? "true" : "false");
    line.kindButton.textContent = "";
    line.kindButton.appendChild(icon(entry.icon));
    line.kindButton.title = entry.label;
    line.kindButton.setAttribute("aria-label", Generic.format(t("Kind of line: %(kind)s"), { kind: entry.label }));
    line.check.hidden = line.kind !== "check";
    line.check.checked = line.done;
    line.input.placeholder = line === this.lines[0] && this.lines.length === 1 ? t("Write something, or /fnc a task...") : "";
    this.paintTask(line);
  };

  NoteEditor.prototype.paintTask = function (line) {
    var self = this;
    var box = line.taskBox;
    var task = line.task;

    box.textContent = "";
    box.taskId = task ? task.id : null;

    if (line.kind !== "task") {
      return;
    }

    var kind = el("span", "tag note-line__task-kind note-line__task-kind--" + (task ? task.kind : line.taskKind).toLowerCase(), task ? task.kind : line.taskKind);

    box.appendChild(kind);

    if (!task) {
      box.appendChild(el("span", "note-line__new muted", t("new task, saved soon")));
      return;
    }

    if (task.url && Generic.isSafeUrl(task.url)) {
      var link = el("a", "note-line__reference", task.reference);

      link.href = task.url;
      link.title = t("Open the task");
      box.appendChild(link);
    } else {
      box.appendChild(el("span", "note-line__reference", task.reference));
    }

    var status = el("select", "input input--sm note-line__status note-line__status--" + task.status);

    status.setAttribute("aria-label", t("Status"));
    status.disabled = !this.canEdit;
    this.statuses.forEach(function (option) {
      var item = el("option", "", option.label);

      item.value = option.value;
      item.selected = option.value === task.status;
      status.appendChild(item);
    });
    status.addEventListener("change", function () {
      self.setStatus(line, status.value);
    });
    box.appendChild(status);

    // A ticket says how bad it is.
    if (task.kind === "FNC" && this.criticalities.length) {
      var criticality = el("select", "input input--sm note-line__criticality note-line__criticality--" + (task.criticality || "none"));

      criticality.setAttribute("aria-label", t("Criticality"));
      criticality.disabled = !this.canEdit;
      this.criticalities.forEach(function (option) {
        var item = el("option", "", option.label);

        item.value = option.value;
        item.selected = option.value === task.criticality;
        criticality.appendChild(item);
      });
      criticality.addEventListener("change", function () {
        self.setTaskField(line, "criticality", criticality.value);
      });
      box.appendChild(criticality);
    }

    var spent = el("span", "note-line__hours", hours(task.hours));

    spent.title = t("Time spent");
    box.appendChild(spent);

    if (this.canTime && task.timerUrl && Generic.isSafeUrl(task.timerUrl)) {
      var timer = el("button", "icon-button icon-button--sm note-line__timer" + (task.running ? " is-running" : ""));

      timer.type = "button";
      timer.appendChild(icon(task.running ? "stop_circle" : "play_circle"));
      timer.title = task.running ? t("Stop the timer") : t("Start the timer");
      timer.setAttribute("aria-label", timer.title);
      timer.setAttribute("aria-pressed", task.running ? "true" : "false");
      timer.addEventListener("click", function () {
        self.toggleTimer(line);
      });
      box.appendChild(timer);
    }
  };

  NoteEditor.prototype.grow = function (line) {
    var input = line.input;

    input.style.height = "auto";
    input.style.height = input.scrollHeight + "px";
  };

  /** A line under this one: a list goes on, anything else is text. */
  NoteEditor.prototype.addBelow = function (line) {
    var kind = line.kind === "bullet" || line.kind === "check" ? line.kind : "text";
    var next = this.blank(kind, line.indent);

    this.clearSelection();
    this.insert(next, this.lines.indexOf(line) + 1);
    this.focus(next, 0);
    this.changed();
  };

  /* -- Kinds, and the line's menu ---------------------------------------- */

  NoteEditor.prototype.menu = function (line, button) {
    var self = this;
    var open = this.element.querySelector(".note-line__menu");

    if (open) {
      open.close();

      if (open.owner === line) {
        return;
      }
    }

    var menu = el("div", "dropdown__menu note-line__menu");

    menu.owner = line;
    menu.setAttribute("role", "menu");
    button.setAttribute("aria-expanded", "true");

    function item(iconName, label, run, options) {
      var entry = el("button", "menu-item" + (options && options.danger ? " menu-item--danger" : ""));

      entry.type = "button";
      entry.setAttribute("role", options && options.checked !== undefined ? "menuitemradio" : "menuitem");

      if (options && options.checked !== undefined) {
        entry.setAttribute("aria-checked", options.checked ? "true" : "false");
      }

      entry.appendChild(icon(iconName));
      entry.appendChild(el("span", "menu-item__label", label));

      if (options && options.hint) {
        entry.appendChild(el("kbd", "menu-item__hint", options.hint));
      }

      entry.addEventListener("click", function () {
        menu.close(true);
        run();
      });
      menu.appendChild(entry);
    }

    KINDS.forEach(function (entry) {
      if (entry.kind === "task" && !self.canAddTasks && !(line.kind === "task" && line.task)) {
        return;
      }

      // A task keeps its kind: its number says FNC, DM or AUT.
      if (line.task && entry.kind === "task" && entry.taskKind !== line.task.kind) {
        return;
      }

      item(
        entry.icon,
        entry.label,
        function () {
          self.setKind(line, entry.kind, entry.taskKind);
          line.input.focus();
        },
        { checked: kindOf(line) === entry }
      );
    });

    menu.appendChild(el("div", "dropdown__divider"));
    item("add", t("Add a line below"), function () {
      self.addBelow(line);
    });
    item(
      "arrow_upward",
      t("Move up"),
      function () {
        self.move(self.block(line), -1);
        line.input.focus();
      },
      { hint: "Alt+Shift+\u2191" }
    );
    item(
      "arrow_downward",
      t("Move down"),
      function () {
        self.move(self.block(line), 1);
        line.input.focus();
      },
      { hint: "Alt+Shift+\u2193" }
    );
    item("select", t("Select the line"), function () {
      self.select(line, line);
    });

    if (this.canAttach) {
      item("attach_file", t("Attach to a task..."), function () {
        self.attach([line]);
      });
    }

    item(
      "delete",
      t("Remove the line"),
      function () {
        self.removeLines([line]);
      },
      { danger: true }
    );

    line.row.appendChild(menu);

    var entries = Array.prototype.slice.call(menu.querySelectorAll(".menu-item"));
    var checked = menu.querySelector('[aria-checked="true"]');

    (checked || entries[0]).focus();

    function close(event) {
      if (event.type === "click" && menu.contains(event.target)) {
        return;
      }

      menu.close();
    }

    menu.close = function (chosen) {
      menu.remove();
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", close);

      if (!chosen) {
        line.input.focus();
      }
    };

    menu.addEventListener("keydown", function (event) {
      var at = entries.indexOf(document.activeElement);
      var to = null;

      if (event.key === "Escape" || event.key === "Tab") {
        event.preventDefault();
        menu.close();
        return;
      }

      if (event.key === "ArrowDown") {
        to = (at + 1) % entries.length;
      } else if (event.key === "ArrowUp") {
        to = (at - 1 + entries.length) % entries.length;
      } else if (event.key === "Home") {
        to = 0;
      } else if (event.key === "End") {
        to = entries.length - 1;
      }

      if (to !== null) {
        event.preventDefault();
        entries[to].focus();
      }
    });

    document.addEventListener("click", close);
  };

  NoteEditor.prototype.setKind = function (line, kind, taskKind) {
    var self = this;

    if (kind === "task" && line.task && line.kind === "task") {
      return;
    }

    if (line.kind === "task" && kind !== "task" && line.task) {
      Generic.dialogs
        .confirm({
          title: Generic.format(t("Turn %(task)s back into text?"), { task: line.task.reference }),
          message: t("The task is kept if time was logged on it or work started; otherwise it is deleted."),
          confirmLabel: t("Make it text"),
          variant: "danger"
        })
        .then(function (confirmed) {
          if (confirmed) {
            line.task = null;
            self.applyKind(line, kind, taskKind);
          }
        });

      return;
    }

    this.applyKind(line, kind, taskKind);
  };

  NoteEditor.prototype.applyKind = function (line, kind, taskKind) {
    line.kind = kind;

    if (taskKind) {
      line.taskKind = taskKind;
    }

    if (kind !== "check") {
      line.done = false;
    }

    this.paint(line);
    this.changed();
  };

  /** The task kind a shortcut gives, when tasks may be made. */
  NoteEditor.prototype.shortcut = function (text) {
    for (var index = 0; index < SHORTCUTS.length; index += 1) {
      var shortcut = SHORTCUTS[index];

      if (shortcut.pattern.test(text)) {
        if (shortcut.kind === "task" && !this.canAddTasks) {
          return null;
        }

        return shortcut;
      }
    }

    return null;
  };

  /* -- Typing ------------------------------------------------------------- */

  NoteEditor.prototype.typed = function (line) {
    var text = line.input.value;
    var shortcut = this.shortcut(text);

    line.text = text;
    this.undoReady = false;

    if (shortcut && (line.kind === "text" || line.kind === "bullet") && !line.task) {
      line.text = text.replace(shortcut.pattern, "");
      line.input.value = line.text;
      line.done = !!shortcut.done;
      this.setKind(line, shortcut.kind, shortcut.taskKind);
    }

    this.grow(line);
    this.changed();
  };

  NoteEditor.prototype.key = function (line, event) {
    var input = line.input;
    var index = this.lines.indexOf(line);
    var start = input.selectionStart;
    var end = input.selectionEnd;
    var length = input.value.length;
    var atStart = start === 0 && end === 0;
    var atEnd = start === length;
    var step = moveStep(event);

    if (command(event) && (event.key === "s" || event.key === "S")) {
      event.preventDefault();
      this.save();
      return;
    }

    // Right after a paste, a move or a removal, Ctrl+Z takes it back;
    // after typing, the browser's own undo takes the typing back.
    if (command(event) && !event.shiftKey && (event.key === "z" || event.key === "Z") && this.undoReady) {
      event.preventDefault();
      this.undo();
      return;
    }

    if (step && this.canEdit) {
      event.preventDefault();
      this.move(this.block(line), step);
      this.focus(line, start);
      return;
    }

    // Shift+Up from a line's start, Shift+Down from its end: lines.
    if (event.key === "ArrowUp" && event.shiftKey && !event.altKey && !command(event) && start === 0 && (end === 0 || input.selectionDirection === "backward")) {
      event.preventDefault();
      this.select(line, this.lines[Math.max(index - 1, 0)]);
      return;
    }

    if (event.key === "ArrowDown" && event.shiftKey && !event.altKey && !command(event) && end === length && (start === length || input.selectionDirection !== "backward")) {
      event.preventDefault();
      this.select(line, this.lines[Math.min(index + 1, this.lines.length - 1)]);
      return;
    }

    // Ctrl+A on a line already all selected: every line.
    if (command(event) && (event.key === "a" || event.key === "A") && start === 0 && end === length) {
      event.preventDefault();
      this.select(this.lines[0], this.lines[this.lines.length - 1]);
      return;
    }

    if (!this.canEdit) {
      return;
    }

    if (event.key === "Enter" && command(event)) {
      event.preventDefault();

      if (line.kind === "check") {
        line.done = !line.done;
        this.paint(line);
        this.changed();
      }

      return;
    }

    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();

      // Enter on an empty list line ends the list.
      if (!input.value && line.kind !== "text" && !line.task) {
        this.setKind(line, "text");
        return;
      }

      var rest = input.value.slice(input.selectionEnd);
      var keep = input.value.slice(0, input.selectionStart);
      var follows = line.kind === "heading" ? "text" : line.kind;

      if (follows === "task" && !this.canAddTasks) {
        follows = "text";
      }

      // Splitting a task line in two would rename its task: the new
      // line takes the rest of the text, the task keeps its own.
      if (!line.task || !rest) {
        line.text = keep;
        input.value = keep;
      } else {
        rest = "";
      }

      var next = this.blank(follows, line.indent, line.taskKind);

      next.text = rest;
      this.insert(next, index + 1);
      this.grow(line);
      this.focus(next, 0);
      this.changed();
      return;
    }

    if (event.key === "Backspace" && atStart) {
      if (line.kind !== "text" && !line.task) {
        event.preventDefault();
        this.setKind(line, "text");
        return;
      }

      if (line.indent > 0) {
        event.preventDefault();
        this.indent(line, -1);
        return;
      }

      if (index > 0 && !line.task) {
        event.preventDefault();

        var previous = this.lines[index - 1];
        var joint = previous.input.value.length;

        previous.text = previous.input.value + input.value;
        previous.input.value = previous.text;
        this.remove(line);
        this.grow(previous);
        this.focus(previous, joint);
        this.changed();
      }

      return;
    }

    if (event.key === "Tab") {
      event.preventDefault();
      this.indent(line, event.shiftKey ? -1 : 1);
      return;
    }

    if (event.key === "ArrowUp" && atStart && index > 0) {
      event.preventDefault();
      this.focus(this.lines[index - 1], null);
      return;
    }

    if (event.key === "ArrowUp" && atStart && index === 0) {
      event.preventDefault();
      this.titleInput.focus();
      return;
    }

    if (event.key === "ArrowDown" && atEnd && index < this.lines.length - 1) {
      event.preventDefault();
      this.focus(this.lines[index + 1], 0);
    }
  };

  /* -- Pasting ------------------------------------------------------------ */

  /** Text into a line, as typed: the browser's undo knows it. */
  function insertText(input, text) {
    input.focus();

    var done = false;

    try {
      done = document.execCommand("insertText", false, text);
    } catch (error) {
      done = false;
    }

    if (!done) {
      input.setRangeText(text, input.selectionStart, input.selectionEnd, "end");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  /** What was copied, read by note-clipboard.js: one line goes into the
   * line, several become lines of the note. */
  NoteEditor.prototype.paste = function (line, event) {
    var data = event.clipboardData;

    if (!this.canEdit || !data) {
      return;
    }

    var pasted = clipboard.read(data);
    var plain = data.getData("text/plain");

    if (!pasted.length) {
      return;
    }

    if (pasted.length === 1) {
      var only = pasted[0];

      // An empty line takes the kind of what is pasted in it.
      if (only.kind !== "text" && !line.input.value && !line.task) {
        event.preventDefault();
        line.done = !!only.done;
        this.applyKind(line, only.kind);
        insertText(line.input, only.text);
        return;
      }

      if (only.text !== plain) {
        event.preventDefault();
        insertText(line.input, only.text);
      }

      return;
    }

    event.preventDefault();
    this.pasteLines(line, pasted);
  };

  /** Lines from the clipboard, a kind each: plain lines pasted in a
   * list keep to the list. */
  NoteEditor.prototype.pastedKind = function (line, pasted) {
    var flat = pasted.every(function (item) {
      return item.kind === "text";
    });

    return function (item) {
      if (flat && (line.kind === "bullet" || line.kind === "check")) {
        return line.kind;
      }

      return item.kind;
    };
  };

  NoteEditor.prototype.pasteLines = function (line, pasted) {
    var input = line.input;
    var before = input.value.slice(0, input.selectionStart);
    var after = input.value.slice(input.selectionEnd);
    var index = this.lines.indexOf(line);
    var base = line.indent;
    var kindFor = this.pastedKind(line, pasted);
    var first = pasted[0];

    this.remember();

    // An empty line becomes the first line pasted; otherwise the first
    // line pasted goes on where the cursor was.
    if (!before.trim() && !line.task) {
      line.kind = kindFor(first);
      line.done = !!first.done;
      line.indent = clampIndent(base + first.indent);
      line.text = first.text;
    } else {
      line.text = before + first.text;
    }

    input.value = line.text;
    this.paint(line);
    this.grow(line);

    var last = this.insertPasted(index + 1, pasted.slice(1), base, kindFor) || line;
    var end = last.text.length;

    last.text += after;
    last.input.value = last.text;
    this.grow(last);
    this.focus(last, end);
    this.changed();
    this.undoReady = true;
    this.offerUndo(Generic.format(Generic.nt("%(count)s line pasted.", "%(count)s lines pasted.", pasted.length), { count: pasted.length }));
  };

  /** Pasted lines put in at an index, indented from `base`; the last
   * one made. */
  NoteEditor.prototype.insertPasted = function (index, pasted, base, kindFor) {
    var self = this;
    var last = null;

    pasted.forEach(function (item) {
      var next = self.blank(kindFor(item), clampIndent(base + item.indent));

      next.text = item.text;
      next.done = !!item.done && next.kind === "check";
      self.insert(next, index);
      index += 1;

      // "/fnc ..." pasted is a task, as typed.
      var shortcut = next.kind === "text" ? self.shortcut(next.text) : null;

      if (shortcut && shortcut.kind === "task") {
        next.text = next.text.replace(shortcut.pattern, "");
        next.input.value = next.text;
        self.applyKind(next, "task", shortcut.taskKind);
      }

      self.grow(next);
      last = next;
    });

    return last;
  };

  /** A paste on selected lines replaces them - task lines stay, the
   * lines pasted go after them. */
  NoteEditor.prototype.pasteOverSelection = function (event) {
    var pasted = clipboard.read(event.clipboardData);
    var selected = this.selectedLines();

    event.preventDefault();

    if (!this.canEdit || !pasted.length || !selected.length) {
      return;
    }

    var first = selected[0];
    var base = first.indent;
    var kept = selected.filter(function (line) {
      return line.task;
    });
    var at = this.lines.indexOf(kept.length ? kept[kept.length - 1] : first);

    this.remember();

    if (!kept.length) {
      at -= 1;
    }

    var self = this;

    selected.forEach(function (line) {
      if (!line.task) {
        self.remove(line);
      }
    });

    at = kept.length ? this.lines.indexOf(kept[kept.length - 1]) + 1 : Math.max(at + 1, 0);

    var last = this.insertPasted(
      at,
      pasted,
      base,
      this.pastedKind(first, pasted)
    );

    this.clearSelection();
    this.focus(last, null);
    this.changed();
    this.undoReady = true;
    this.offerUndo(Generic.format(Generic.nt("%(count)s line pasted.", "%(count)s lines pasted.", pasted.length), { count: pasted.length }));
  };

  /* -- Copying ---------------------------------------------------------------- */

  NoteEditor.prototype.plain = function (lines) {
    return lines.map(function (line) {
      return {
        kind: line.kind,
        indent: line.indent,
        text: line.input ? line.input.value : line.text,
        done: line.done,
        reference: line.task ? line.task.reference : ""
      };
    });
  };

  /** Ctrl+C, Ctrl+X on selected lines, or the copy button. */
  NoteEditor.prototype.copied = function (event, cut) {
    var lines = this.copying;

    if (!lines && this.selection && document.activeElement === this.list) {
      lines = this.selectedLines();
    }

    if (!lines || !event.clipboardData) {
      return;
    }

    var written = clipboard.write(this.plain(lines));

    event.preventDefault();
    event.clipboardData.setData("text/plain", written.text);
    event.clipboardData.setData("text/html", written.html);
    this.copying = null;
    this.copiedCount = lines.length;

    if (cut && this.canEdit) {
      this.removeLines(lines, { cut: true });
    }
  };

  NoteEditor.prototype.copyLines = function (lines) {
    var self = this;
    var count = lines.length;
    var done = false;

    this.copying = lines;

    try {
      done = document.execCommand("copy");
    } catch (error) {
      done = false;
    }

    // Asked for, and not given: the asynchronous clipboard, when there
    // is one (a secure page).
    if (this.copying) {
      var written = clipboard.write(this.plain(lines));

      this.copying = null;

      if (window.navigator.clipboard && window.ClipboardItem) {
        window.navigator.clipboard
          .write([
            new window.ClipboardItem({
              "text/plain": new Blob([written.text], { type: "text/plain" }),
              "text/html": new Blob([written.html], { type: "text/html" })
            })
          ])
          .then(function () {
            self.copiedToast(count);
          })
          .catch(function () {
            Generic.toast(t("The lines could not be copied: select them and press Ctrl+C."), "error");
          });

        return;
      }

      done = false;
    }

    if (done) {
      this.copiedToast(count);
    } else {
      Generic.toast(t("The lines could not be copied: select them and press Ctrl+C."), "error");
    }
  };

  NoteEditor.prototype.copiedToast = function (count) {
    Generic.toast(Generic.format(Generic.nt("%(count)s line copied.", "%(count)s lines copied.", count), { count: count }), "success");
  };

  /* -- Selecting lines --------------------------------------------------- */

  NoteEditor.prototype.select = function (anchor, focus) {
    this.selection = { anchor: anchor, focus: focus || anchor };
    this.paintSelection();
    this.list.focus({ preventScroll: true });
    this.reveal(this.selection.focus);
  };

  NoteEditor.prototype.clearSelection = function () {
    if (!this.selection) {
      return;
    }

    this.selection = null;
    this.paintSelection();
  };

  NoteEditor.prototype.selectedLines = function () {
    if (!this.selection) {
      return [];
    }

    var from = this.lines.indexOf(this.selection.anchor);
    var to = this.lines.indexOf(this.selection.focus);

    if (from === -1 || to === -1) {
      return [];
    }

    return this.lines.slice(Math.min(from, to), Math.max(from, to) + 1);
  };

  NoteEditor.prototype.paintSelection = function () {
    var selected = this.selectedLines();

    this.lines.forEach(function (line) {
      var on = selected.indexOf(line) !== -1;

      line.row.classList.toggle("is-selected", on);
      line.row.setAttribute("aria-selected", on ? "true" : "false");
    });

    this.list.classList.toggle("has-selection", selected.length > 0);

    if (selected.length) {
      this.showStatus(Generic.format(Generic.nt("%(count)s line selected", "%(count)s lines selected", selected.length), { count: selected.length }));
    } else if (!this.dirty && !this.saving) {
      this.showStatus(this.savedText || t("Saved"));
    }
  };

  NoteEditor.prototype.reveal = function (line) {
    if (line && line.row && line.row.scrollIntoView) {
      line.row.scrollIntoView({ block: "nearest" });
    }
  };

  NoteEditor.prototype.handleClicked = function (line, event) {
    if (event.shiftKey && (this.selection || this.current)) {
      this.select(this.selection ? this.selection.anchor : this.current, line);
      return;
    }

    if (this.selection && this.selectedLines().length === 1 && this.selection.anchor === line) {
      this.clearSelection();
      this.focus(line, null);
      return;
    }

    this.select(line, line);
  };

  /** Keys while whole lines are selected (the list has the focus). */
  NoteEditor.prototype.selectionKey = function (event) {
    var selected = this.selectedLines();
    var focus = this.selection ? this.selection.focus : null;
    var step = moveStep(event);

    if (!selected.length) {
      return;
    }

    if (step) {
      event.preventDefault();

      if (this.canEdit) {
        this.move(selected, step);
      }

      return;
    }

    var at = this.lines.indexOf(focus);

    switch (event.key) {
      case "Escape":
      case "Enter":
        event.preventDefault();
        this.clearSelection();
        this.focus(focus, null);
        return;
      case "ArrowUp":
      case "ArrowDown":
        event.preventDefault();

        if (event.shiftKey) {
          var to = this.lines[Math.min(Math.max(at + (event.key === "ArrowUp" ? -1 : 1), 0), this.lines.length - 1)];

          this.selection.focus = to;
          this.paintSelection();
          this.reveal(to);
        } else {
          var edge = event.key === "ArrowUp" ? selected[0] : selected[selected.length - 1];

          this.clearSelection();
          this.focus(edge, event.key === "ArrowUp" ? 0 : null);
        }

        return;
      case "Tab":
        event.preventDefault();

        if (this.canEdit) {
          this.indentLines(selected, event.shiftKey ? -1 : 1);
        }

        return;
      case "Backspace":
      case "Delete":
        event.preventDefault();

        if (this.canEdit) {
          this.removeLines(selected);
        }

        return;
      default:
        break;
    }

    if (command(event) && (event.key === "a" || event.key === "A")) {
      event.preventDefault();
      this.select(this.lines[0], this.lines[this.lines.length - 1]);
      return;
    }

    if (command(event) && !event.shiftKey && (event.key === "z" || event.key === "Z")) {
      event.preventDefault();
      this.undo();
    }
  };

  /* -- Moving and removing lines -------------------------------------------- */

  /** A line and the lines indented under it. */
  NoteEditor.prototype.block = function (line) {
    var index = this.lines.indexOf(line);
    var block = [line];

    for (var next = index + 1; next < this.lines.length && this.lines[next].indent > line.indent; next += 1) {
      block.push(this.lines[next]);
    }

    return block;
  };

  /** Lines (one after the other) moved past their neighbour - with the
   * neighbour's own indented lines - up (-1) or down (1). */
  NoteEditor.prototype.move = function (lines, step) {
    var first = this.lines.indexOf(lines[0]);
    var last = first + lines.length - 1;
    var target;

    if (first === -1) {
      return;
    }

    if (step < 0) {
      if (first === 0) {
        return;
      }

      // Up past the previous line at most as deep, and what is under it.
      target = first - 1;

      while (target > 0 && this.lines[target].indent > lines[0].indent) {
        target -= 1;
      }
    } else {
      if (last >= this.lines.length - 1) {
        return;
      }

      var after = this.block(this.lines[last + 1]);

      target = last + after.length + 1 - lines.length;
    }

    this.remember();
    this.moveTo(lines, target);
    this.undoReady = true;
  };

  /** Lines moved so the first one sits at `index` once they are out. */
  NoteEditor.prototype.moveTo = function (lines, index) {
    var self = this;

    lines.forEach(function (line) {
      self.lines.splice(self.lines.indexOf(line), 1);
    });
    Array.prototype.splice.apply(this.lines, [index, 0].concat(lines));
    this.redraw();
    this.reveal(lines[0]);
    this.changed();
  };

  NoteEditor.prototype.redraw = function () {
    var self = this;

    this.lines.forEach(function (line) {
      self.list.appendChild(line.row);
    });
    this.paint(this.lines[0]);
    this.paintSelection();
  };

  NoteEditor.prototype.indentLines = function (lines, step) {
    var self = this;

    lines.forEach(function (line) {
      self.indent(line, step);
    });
  };

  /** Lines taken out of the note - asked first when tasks go with them. */
  NoteEditor.prototype.removeLines = function (lines, options) {
    var self = this;
    var tasks = lines
      .filter(function (line) {
        return line.task;
      })
      .map(function (line) {
        return line.task.reference;
      });

    function go() {
      var index = self.lines.indexOf(lines[0]);

      self.remember();
      self.clearSelection();
      lines.forEach(function (line) {
        self.remove(line);
      });

      if (!self.lines.length) {
        self.insert(self.blank(), 0);
      }

      var next = self.lines[Math.min(Math.max(index, 0), self.lines.length - 1)];

      self.paint(self.lines[0]);
      self.focus(next, 0);
      self.changed();
      self.undoReady = true;
      self.offerUndo(
        Generic.format(
          options && options.cut
            ? Generic.nt("%(count)s line cut.", "%(count)s lines cut.", lines.length)
            : Generic.nt("%(count)s line removed.", "%(count)s lines removed.", lines.length),
          { count: lines.length }
        )
      );
    }

    if (!tasks.length) {
      go();
      return;
    }

    Generic.dialogs
      .confirm({
        title: Generic.format(Generic.nt("Remove %(count)s line?", "Remove %(count)s lines?", lines.length), { count: lines.length }),
        message: Generic.format(t("With them go the lines of %(tasks)s: each task is kept if time was logged on it or work started; otherwise it is deleted."), {
          tasks: tasks.join(", ")
        }),
        confirmLabel: t("Remove"),
        variant: "danger"
      })
      .then(function (confirmed) {
        if (confirmed) {
          go();
        } else {
          self.list.focus();
        }
      });
  };

  /* -- Dragging ---------------------------------------------------------- */

  NoteEditor.prototype.dragStart = function (line, event) {
    if (!this.canEdit) {
      event.preventDefault();
      return;
    }

    var selected = this.selectedLines();
    var lines = selected.indexOf(line) !== -1 ? selected : this.block(line);

    this.dragging = lines;
    lines.forEach(function (item) {
      item.row.classList.add("is-dragging");
    });

    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", clipboard.toText(this.plain(lines)));

    if (event.dataTransfer.setDragImage) {
      event.dataTransfer.setDragImage(line.row, 16, 16);
    }
  };

  NoteEditor.prototype.dragEnd = function () {
    if (this.dragging) {
      this.dragging.forEach(function (item) {
        item.row.classList.remove("is-dragging");
      });
    }

    this.dragging = null;
    this.dropMark(null);
  };

  /** Where a drop at this height lands: before or after which line. */
  NoteEditor.prototype.dropAt = function (y) {
    for (var index = 0; index < this.lines.length; index += 1) {
      var box = this.lines[index].row.getBoundingClientRect();

      if (y < box.top + box.height / 2) {
        return { line: this.lines[index], after: false };
      }
    }

    return { line: this.lines[this.lines.length - 1], after: true };
  };

  NoteEditor.prototype.dropMark = function (at) {
    var marked = this.list.querySelectorAll(".is-drop-before, .is-drop-after");

    Array.prototype.forEach.call(marked, function (row) {
      row.classList.remove("is-drop-before", "is-drop-after");
    });

    if (at) {
      at.line.row.classList.add(at.after ? "is-drop-after" : "is-drop-before");
    }
  };

  NoteEditor.prototype.dragAndDrop = function () {
    var self = this;

    this.list.addEventListener("dragover", function (event) {
      if (!self.dragging) {
        return;
      }

      event.preventDefault();
      event.dataTransfer.dropEffect = "move";

      var at = self.dropAt(event.clientY);

      self.dropMark(self.dragging.indexOf(at.line) === -1 ? at : null);
    });

    this.list.addEventListener("dragleave", function (event) {
      if (self.dragging && !self.list.contains(event.relatedTarget)) {
        self.dropMark(null);
      }
    });

    this.list.addEventListener("drop", function (event) {
      if (!self.dragging) {
        return;
      }

      event.preventDefault();

      var lines = self.dragging;
      var at = self.dropAt(event.clientY);

      self.dragEnd();

      if (lines.indexOf(at.line) !== -1) {
        return;
      }

      var rest = self.lines.filter(function (line) {
        return lines.indexOf(line) === -1;
      });
      var index = rest.indexOf(at.line) + (at.after ? 1 : 0);

      self.remember();
      self.moveTo(lines, index);
      self.undoReady = true;
      self.offerUndo(Generic.format(Generic.nt("%(count)s line moved.", "%(count)s lines moved.", lines.length), { count: lines.length }));
    });
  };

  /* -- Undo ---------------------------------------------------------------- */

  /** The note as it is, kept to come back to. The line objects are kept
   * themselves: what a save gives them meanwhile (an id, a task) stays
   * theirs. */
  NoteEditor.prototype.remember = function () {
    var focused = this.current && this.lines.indexOf(this.current) !== -1 ? this.current : null;

    this.history.push({
      focus: focused,
      caret: focused ? focused.input.selectionStart : 0,
      lines: this.lines.map(function (line) {
        return {
          line: line,
          kind: line.kind,
          indent: line.indent,
          text: line.input ? line.input.value : line.text,
          done: line.done,
          task: line.task,
          taskKind: line.taskKind
        };
      })
    });

    if (this.history.length > UNDO_DEPTH) {
      this.history.shift();
    }
  };

  NoteEditor.prototype.undo = function () {
    var self = this;
    var state = this.history.pop();

    this.undoReady = false;

    if (!state) {
      return;
    }

    this.clearSelection();
    this.list.textContent = "";
    this.lines = state.lines.map(function (kept) {
      var line = kept.line;

      line.kind = kept.kind;
      line.indent = kept.indent;
      line.text = kept.text;
      line.done = kept.done;
      line.taskKind = kept.taskKind;
      line.task = line.task || kept.task;
      line.input.value = kept.text;

      return line;
    });
    this.lines.forEach(function (line) {
      self.list.appendChild(line.row);
      self.paint(line);
    });
    this.lines.forEach(function (line) {
      self.grow(line);
    });
    if (state.focus) {
      this.focus(state.focus, state.caret);
    } else {
      this.focus(this.lines[0], 0);
    }

    this.changed();
    this.undoReady = this.history.length > 0;
  };

  NoteEditor.prototype.offerUndo = function (message) {
    var self = this;
    var depth = this.history.length;

    Generic.toast(message, "info", {
      action: {
        label: t("Undo"),
        icon: "undo",
        run: function () {
          // Only the latest change is undone from its toast.
          if (self.history.length === depth) {
            self.undo();
          }
        }
      }
    });
  };

  /* -- Indenting, inserting ------------------------------------------------ */

  NoteEditor.prototype.indent = function (line, step) {
    var indent = clampIndent(line.indent + step);

    if (indent !== line.indent) {
      line.indent = indent;
      this.paint(line);
      this.changed();
    }
  };

  NoteEditor.prototype.insert = function (line, index) {
    var row = this.row(line);
    var before = this.lines[index];

    this.lines.splice(index, 0, line);
    this.list.insertBefore(row, before ? before.row : null);
    this.paint(this.lines[0]);
  };

  NoteEditor.prototype.remove = function (line) {
    var index = this.lines.indexOf(line);

    if (index !== -1) {
      this.lines.splice(index, 1);
      line.row.remove();
    }

    if (this.current === line) {
      this.current = null;
    }
  };

  NoteEditor.prototype.focus = function (line, position) {
    if (!line) {
      return;
    }

    var input = line.input;
    var at = position === null ? input.value.length : Math.min(position, input.value.length);

    input.focus();
    input.setSelectionRange(at, at);
  };

  /* -- Attaching lines to a task ------------------------------------------- */

  /** The lines' text added to a task's specification - a task picked in
   * a dialog, searched by reference or title. */
  NoteEditor.prototype.attach = function (lines) {
    var self = this;
    var written = this.plain(lines).filter(function (line) {
      return line.text.trim();
    });

    if (!this.canAttach) {
      return;
    }

    if (!written.length) {
      Generic.toast(t("Nothing to attach: write or select the lines first."), "warning");
      return;
    }

    var text = clipboard.toText(written, { indent: "  " });
    var dialog = Generic.dialogs.open({ title: t("Attach to a task"), icon: "attach_file", wide: true });
    var preview = el("pre", "note-attach__preview", text);
    var search = el("input", "input");
    var results = el("div", "note-attach__results");
    var chosen = null;
    var options = [];
    var cancel = el("button", "button button--ghost", t("Cancel"));
    var accept = el("button", "button button--primary", t("Attach"));
    var waiting = null;

    dialog.body.appendChild(
      el(
        "p",
        "muted",
        Generic.format(
          Generic.nt(
            "This line is added to the specification of the task you pick, with the note's title and today's date.",
            "These %(count)s lines are added to the specification of the task you pick, with the note's title and today's date.",
            written.length
          ),
          { count: written.length }
        )
      )
    );
    dialog.body.appendChild(preview);

    var field = el("label", "sf-field note-attach__search");

    field.appendChild(el("span", "sf-label", t("Task")));
    search.type = "search";
    search.placeholder = t("Search by reference or title");
    search.setAttribute("aria-controls", "note-attach-results");
    search.autocomplete = "off";
    field.appendChild(search);
    dialog.body.appendChild(field);
    results.id = "note-attach-results";
    results.setAttribute("role", "listbox");
    results.setAttribute("aria-label", t("Tasks"));
    dialog.body.appendChild(results);

    cancel.type = "button";
    accept.type = "button";
    accept.disabled = true;
    cancel.addEventListener("click", function () {
      dialog.close(null);
    });
    accept.addEventListener("click", send);
    dialog.footer.appendChild(cancel);
    dialog.footer.appendChild(accept);

    function pick(option) {
      chosen = option ? option.task : null;
      options.forEach(function (other) {
        other.node.setAttribute("aria-selected", other === option ? "true" : "false");
      });
      accept.disabled = !chosen;

      if (option) {
        option.node.scrollIntoView({ block: "nearest" });
      }
    }

    function draw(tasks) {
      results.textContent = "";
      options = [];

      if (!tasks.length) {
        results.appendChild(el("p", "muted note-attach__empty", t("No task found.")));
        pick(null);
        return;
      }

      tasks.forEach(function (task) {
        var node = el("button", "note-attach__option");
        var option = { task: task, node: node };

        node.type = "button";
        node.setAttribute("role", "option");
        node.appendChild(el("span", "tag note-line__task-kind note-line__task-kind--" + String(task.kind).toLowerCase(), task.reference));
        node.appendChild(el("span", "note-attach__title", task.title));
        node.appendChild(el("span", "muted note-attach__status", task.statusLabel));
        node.addEventListener("click", function () {
          pick(option);
        });
        node.addEventListener("dblclick", function () {
          pick(option);
          send();
        });
        results.appendChild(node);
        options.push(option);
      });

      // A search typed: its best match is picked, Enter attaches.
      pick(search.value.trim() ? options[0] : null);
    }

    function load() {
      var asked = search.value.trim();

      Generic.api
        .get(self.attachUrl, { q: asked })
        .then(function (answer) {
          if (search.value.trim() === asked) {
            draw(answer.tasks || []);
          }
        })
        .catch(function (error) {
          results.textContent = "";
          results.appendChild(el("p", "callout callout--danger", (error && error.message) || t("The tasks could not be loaded.")));
        });
    }

    function send() {
      if (!chosen) {
        return;
      }

      var task = chosen;

      accept.disabled = true;
      Generic.api
        .post(self.attachUrl, { task: task.id, text: text })
        .then(function (answer) {
          dialog.close(true);
          Generic.toast(
            Generic.format(t("Added to the specification of %(task)s."), { task: answer.reference || task.reference }),
            "success",
            answer.url && Generic.isSafeUrl(answer.url)
              ? {
                  action: {
                    label: t("Open"),
                    icon: "open_in_new",
                    run: function () {
                      window.location.href = answer.url;
                    }
                  }
                }
              : {}
          );
        })
        .catch(function (error) {
          accept.disabled = false;
          Generic.toast((error && error.message) || t("The text could not be attached."), "error");
        });
    }

    search.addEventListener("input", function () {
      window.clearTimeout(waiting);
      waiting = window.setTimeout(load, 200);
    });
    search.addEventListener("keydown", function (event) {
      var at = -1;

      options.forEach(function (option, index) {
        if (option.task === chosen) {
          at = index;
        }
      });

      if (event.key === "ArrowDown" && options.length) {
        event.preventDefault();
        pick(options[Math.min(at + 1, options.length - 1)]);
      } else if (event.key === "ArrowUp" && options.length) {
        event.preventDefault();
        pick(options[Math.max(at - 1, 0)]);
      } else if (event.key === "Enter") {
        event.preventDefault();
        send();
      }
    });

    dialog.closed.then(function () {
      if (self.selection) {
        self.list.focus();
      } else if (self.current) {
        self.focus(self.current, null);
      }
    });

    search.focus();
    load();
  };

  /* -- Saving -------------------------------------------------------------- */

  NoteEditor.prototype.changed = function () {
    var self = this;

    if (!this.canEdit) {
      return;
    }

    this.dirty = true;
    this.showStatus(t("Not saved yet"));
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(function () {
      self.save();
    }, SAVE_DELAY);
  };

  NoteEditor.prototype.showStatus = function (text, level) {
    this.status.textContent = text;
    this.status.className = "note-editor__status " + (level === "error" ? "note-editor__status--error" : "muted");
  };

  NoteEditor.prototype.save = function () {
    var self = this;

    window.clearTimeout(this.timer);

    if (!this.canEdit || !this.dirty) {
      return;
    }

    if (this.saving) {
      this.again = true;
      return;
    }

    var sent = this.lines.slice();
    var body = {
      title: this.titleInput.value,
      lines: sent.map(function (line) {
        return {
          id: line.id,
          kind: line.kind,
          indent: line.indent,
          text: line.text,
          done: line.done,
          taskKind: line.taskKind
        };
      })
    };

    this.dirty = false;
    this.showStatus(t("Saving..."));
    this.saving = Generic.api
      .post(this.url, body)
      .then(function (answer) {
        var tasksMoved = false;

        // Lines come back in the order they went: each takes its key,
        // and its task - what was typed meanwhile stays as typed.
        (answer.lines || []).forEach(function (stored, index) {
          var line = sent[index];

          if (!line) {
            return;
          }

          line.id = stored.id;

          if (line.kind === "task") {
            var before = line.task ? line.task.id : null;

            line.task = stored.task;

            if (stored.task && before !== stored.task.id) {
              tasksMoved = true;
            }

            if (line.taskBox && line.taskBox.taskId !== (stored.task ? stored.task.id : null)) {
              self.paintTask(line);
            }
          } else {
            tasksMoved = tasksMoved || !!line.task;
            line.task = null;
          }
        });

        // The note's tables below - its tasks - show the new ones.
        if (tasksMoved || sent.length !== (answer.lines || []).length) {
          document.dispatchEvent(new CustomEvent("generic:tables-reload"));
        }

        var now = new Date();

        self.savedText = Generic.format(t("Saved at %(time)s"), {
          time: now.toLocaleTimeString(document.documentElement.lang || undefined, { hour: "2-digit", minute: "2-digit" })
        });

        if (!self.selection && !self.dirty) {
          self.showStatus(self.savedText);
        }

        self.element.dispatchEvent(new CustomEvent("planner:note-saved", { bubbles: true }));
      })
      .catch(function (error) {
        self.dirty = true;
        self.showStatus((error && error.message) || t("The note could not be saved."), "error");
        Generic.toast((error && error.message) || t("The note could not be saved."), "error");
      })
      .then(function () {
        self.saving = null;

        if (self.again) {
          self.again = false;
          self.save();
        }
      });
  };

  /* -- A task's status and timer --------------------------------------------- */

  NoteEditor.prototype.setStatus = function (line, status) {
    this.setTaskField(line, "status", status);
  };

  NoteEditor.prototype.setTaskField = function (line, name, value) {
    var self = this;
    var task = line.task;
    var body = {};

    if (!task || !task.api) {
      return;
    }

    body[name] = value;
    Generic.api
      .patch(task.api, body)
      .then(function () {
        task[name] = value;
        self.paintTask(line);
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The task could not be changed."), "error");
        self.paintTask(line);
      });
  };

  NoteEditor.prototype.toggleTimer = function (line) {
    var self = this;
    var task = line.task;

    Generic.api
      .post(task.timerUrl, {})
      .then(function (answer) {
        self.lines.forEach(function (other) {
          if (other.task && other.task.running && other !== line) {
            other.task.running = false;
            self.paintTask(other);
          }
        });
        task.running = !!answer.running;
        task.hours = answer.hours;
        self.paintTask(line);
        Generic.toast(
          answer.running
            ? Generic.format(t("The timer runs on %(task)s."), { task: task.reference })
            : Generic.format(t("Time logged on %(task)s."), { task: task.reference }),
          "success"
        );
      })
      .catch(function (error) {
        Generic.toast((error && error.message) || t("The timer could not be changed."), "error");
      });
  };

  function start(element) {
    if (!element || element.noteEditor || !element.getAttribute("data-url")) {
      return null;
    }

    var editor = new NoteEditor(element);

    element.noteEditor = editor;
    editor.start();

    return editor;
  }

  Generic.noteEditor = { start: start };

  Generic.ready(function () {
    Array.prototype.forEach.call(document.querySelectorAll(".note-editor[data-url]"), start);
  });
})(window, document);

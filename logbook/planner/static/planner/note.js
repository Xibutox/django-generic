/**
 * The note editor: a note written line by line.
 *
 * Each line is a kind - text, heading, bullet, to-do, or task - and a
 * task line is a task: saved once, it is numbered (FNC-0007, DM-0003),
 * shows its status, the time spent on it, and a button starting or
 * stopping the timer. Typing at the start of a line changes its kind:
 * "# " a heading, "- " a bullet, "[] " a to-do, "/fnc ", "/dm " or "/aut " a
 * task. Enter starts a line, Backspace on an empty one removes it, Tab
 * and Shift+Tab indent. The note saves itself a moment after the last
 * change (Ctrl+S at once): the whole note is posted to its document
 * page (planner/documents.py), which answers what it stored.
 *
 *   <section class="note-editor" data-url="<the note's document page>">
 *
 * Text reaches the page through textContent and form values, addresses
 * through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var KINDS = [
    { kind: "text", icon: "notes", label: t("Text") },
    { kind: "heading", icon: "title", label: t("Heading") },
    { kind: "bullet", icon: "format_list_bulleted", label: t("Bullet") },
    { kind: "check", icon: "check_box", label: t("To-do") },
    { kind: "task", taskKind: "FNC", icon: "bug_report", label: t("FNC task - a ticket") },
    { kind: "task", taskKind: "DM", icon: "rocket_launch", label: t("DM task - an evolution") },
    { kind: "task", taskKind: "AUT", icon: "groups", label: t("AUT task - a meeting, support") }
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

  var SAVE_DELAY = 900;
  var MAX_INDENT = 4;
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

  /* -- The editor ------------------------------------------------------ */

  function NoteEditor(element) {
    this.element = element;
    this.url = element.getAttribute("data-url");
    this.lines = [];
    this.timer = null;
    this.saving = null;
    this.dirty = false;
    this.again = false;
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
  };

  NoteEditor.prototype.load = function (answer) {
    this.canEdit = !!answer.canEdit;
    this.canAddTasks = !!answer.canAddTasks;
    this.canTime = !!answer.canTime;
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

    this.list = el("div", "note-editor__lines");
    this.list.setAttribute("role", "list");
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

  /* -- A line ------------------------------------------------------------ */

  NoteEditor.prototype.row = function (line) {
    var self = this;
    var row = el("div", "note-line");
    var kind = el("button", "note-line__kind icon-button icon-button--sm");
    var text = el("textarea", "note-line__text");

    row.setAttribute("role", "listitem");
    line.row = row;
    line.input = text;
    kind.type = "button";
    kind.disabled = !this.canEdit;
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

    row.className = "note-line note-line--" + line.kind + (line.done ? " is-done" : "");
    row.style.setProperty("--indent", String(line.indent));
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

  /* -- Kinds ------------------------------------------------------------- */

  NoteEditor.prototype.menu = function (line, button) {
    var self = this;
    var open = this.element.querySelector(".note-line__menu");

    if (open) {
      open.remove();

      if (open.owner === line) {
        return;
      }
    }

    var menu = el("div", "dropdown__menu note-line__menu");

    menu.owner = line;
    menu.setAttribute("role", "menu");

    KINDS.forEach(function (entry) {
      if (entry.kind === "task" && !self.canAddTasks && !(line.kind === "task" && line.task)) {
        return;
      }

      // A task keeps its kind: its number says FNC, DM or AUT.
      if (line.task && entry.kind === "task" && entry.taskKind !== line.task.kind) {
        return;
      }

      var item = el("button", "menu-item");

      item.type = "button";
      item.setAttribute("role", "menuitemradio");
      item.setAttribute("aria-checked", kindOf(line) === entry ? "true" : "false");
      item.appendChild(icon(entry.icon));
      item.appendChild(el("span", "menu-item__label", entry.label));
      item.addEventListener("click", function () {
        menu.remove();
        self.setKind(line, entry.kind, entry.taskKind);
        line.input.focus();
      });
      menu.appendChild(item);
    });

    line.row.appendChild(menu);

    var first = menu.querySelector("button");

    if (first) {
      first.focus();
    }

    function close(event) {
      if (event.type === "keydown" && event.key !== "Escape") {
        return;
      }

      if (event.type === "click" && menu.contains(event.target)) {
        return;
      }

      menu.remove();
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", close);
    }

    document.addEventListener("click", close);
    document.addEventListener("keydown", close);
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

  /* -- Typing ------------------------------------------------------------- */

  NoteEditor.prototype.typed = function (line) {
    var text = line.input.value;

    line.text = text;

    for (var index = 0; index < SHORTCUTS.length; index += 1) {
      var shortcut = SHORTCUTS[index];

      if (shortcut.pattern.test(text) && (line.kind === "text" || line.kind === "bullet") && !line.task) {
        if (shortcut.kind === "task" && !this.canAddTasks) {
          break;
        }

        line.text = text.replace(shortcut.pattern, "");
        line.input.value = line.text;
        line.done = !!shortcut.done;
        this.setKind(line, shortcut.kind, shortcut.taskKind);
        break;
      }
    }

    this.grow(line);
    this.changed();
  };

  NoteEditor.prototype.key = function (line, event) {
    var input = line.input;
    var index = this.lines.indexOf(line);
    var atStart = input.selectionStart === 0 && input.selectionEnd === 0;
    var atEnd = input.selectionStart === input.value.length;

    if ((event.ctrlKey || event.metaKey) && (event.key === "s" || event.key === "S")) {
      event.preventDefault();
      this.save();
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

  /** Several lines pasted: several lines of the note. */
  NoteEditor.prototype.paste = function (line, event) {
    var data = event.clipboardData && event.clipboardData.getData("text/plain");

    if (!data || data.indexOf("\n") === -1 || !this.canEdit) {
      return;
    }

    event.preventDefault();

    var input = line.input;
    var parts = data.replace(/\r\n?/g, "\n").split("\n");
    var before = input.value.slice(0, input.selectionStart);
    var after = input.value.slice(input.selectionEnd);
    var index = this.lines.indexOf(line);
    var last = line;

    line.text = before + parts[0];
    input.value = line.text;
    this.grow(line);

    for (var part = 1; part < parts.length; part += 1) {
      var next = this.blank(line.kind === "task" || line.kind === "heading" ? "text" : line.kind, line.indent);

      next.text = parts[part];
      index += 1;
      this.insert(next, index);
      this.typed(next);
      last = next;
    }

    var end = last.text.length;

    last.text += after;
    last.input.value = last.text;
    this.grow(last);
    this.focus(last, end);
    this.changed();
  };

  NoteEditor.prototype.indent = function (line, step) {
    var indent = Math.min(Math.max(line.indent + step, 0), MAX_INDENT);

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
  };

  NoteEditor.prototype.focus = function (line, position) {
    if (!line) {
      return;
    }

    var input = line.input;
    var at = position === null ? input.value.length : position;

    input.focus();
    input.setSelectionRange(at, at);
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
            var wasNew = !line.task;

            line.task = stored.task;

            if (wasNew && stored.task) {
              tasksMoved = true;
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

        self.showStatus(
          Generic.format(t("Saved at %(time)s"), {
            time: now.toLocaleTimeString(document.documentElement.lang || undefined, { hour: "2-digit", minute: "2-digit" })
          })
        );
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

/**
 * The wiki: a page, its editor, and the menu of pages.
 *
 * Reading needs nothing but the page itself. Editing starts Quill - a
 * rich-text editor - on the page's content and saves through the wiki
 * API as JSON. The server cleans the HTML before storing it and again
 * before showing it: the editor is a convenience, not a gatekeeper.
 *
 * Images and files are uploaded from the editor - its toolbar, a drop,
 * a paste - and put where the cursor (or the drop) is: an image in the
 * text, a file as a block of its own linking to it. Any line, block or
 * image moves up and down the page with the toolbar's arrows or
 * Alt+Up / Alt+Down, so the page is ordered the way its writer wants.
 *
 * The list of wikis (`wikiList`) creates, renames and deletes them,
 * through the same API.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var TOOLBAR = [
    [{ header: [2, 3, 4, false] }],
    ["bold", "italic", "underline", "strike", "code"],
    [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
    ["blockquote", "code-block", "link", "image", "attach"],
    [{ align: [] }],
    ["moveUp", "moveDown"],
    ["clean"]
  ];

  //: The toolbar's own buttons, which Quill has no icon for.
  var BUTTONS = {
    attach: { icon: "attach_file", label: "Attach a file" },
    moveUp: { icon: "arrow_upward", label: "Move up (Alt+Up)" },
    moveDown: { icon: "arrow_downward", label: "Move down (Alt+Down)" }
  };

  //: The images a page may hold, as the upload endpoint takes them.
  var IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  var IMAGE_NAME = /\.(png|jpe?g|gif|webp)$/i;

  function icon(name) {
    var node = el("span", "icon material-symbols-outlined", name);
    node.setAttribute("aria-hidden", "true");

    return node;
  }

  /**
   * A file in the page: a paragraph of its own, holding the link to
   * it - ``<p class="wiki-file"><a href="/wiki/files/7/">plan.pdf</a>``
   * - which the server's cleaning keeps. One block for the editor: it
   * moves, and is deleted, as a whole.
   */
  function registerFileBlock(Quill) {
    if (Quill.imports["formats/wikiFile"]) {
      return;
    }

    var BlockEmbed = Quill.import("blots/block/embed");

    // Quill's blots are classes; this is how ES5 extends one.
    function FileBlock(scroll, node) {
      return Reflect.construct(BlockEmbed, [scroll, node], FileBlock);
    }

    Object.setPrototypeOf(FileBlock.prototype, BlockEmbed.prototype);
    Object.setPrototypeOf(FileBlock, BlockEmbed);
    FileBlock.blotName = "wikiFile";
    FileBlock.tagName = "P";
    FileBlock.className = "wiki-file";

    FileBlock.create = function (value) {
      var node = BlockEmbed.create.call(this, value);
      var link = document.createElement("a");

      link.setAttribute("href", value.url);
      link.textContent = value.name || value.url;
      node.appendChild(link);
      node.setAttribute("contenteditable", "false");

      return node;
    };

    FileBlock.value = function (node) {
      var link = node.querySelector("a");

      return {
        url: link ? link.getAttribute("href") : "",
        name: link ? link.textContent : ""
      };
    };

    // What the page stores: the block without the editor's attributes.
    FileBlock.prototype.html = function () {
      var node = this.domNode.cloneNode(true);

      node.removeAttribute("contenteditable");

      return node.outerHTML;
    };

    Quill.register(FileBlock);
  }

  /**
   * Swap the line holding the cursor with the one above (`step` -1) or
   * below (+1): a paragraph, a heading, a list item, an image on its
   * line, a file. As the writer's own edit, so Ctrl+Z undoes it.
   */
  function moveLine(quill, step) {
    var range = quill.getSelection(true);

    if (!range) {
      return;
    }

    var lines = quill.getLines(0, quill.getLength());
    var line = quill.getLine(range.index)[0];
    var at = lines.indexOf(line);
    var other = lines[at + step];

    if (at === -1 || !other) {
      return;
    }

    // Moving a line down is moving the next one up.
    var upper = step < 0 ? other : line;
    var lower = step < 0 ? line : other;
    var upperStart = quill.getIndex(upper);
    var lowerStart = quill.getIndex(lower);
    var lowerLength = lower.length();
    var moved = quill.getContents(lowerStart, lowerLength);
    var Delta = window.Quill.import("delta");
    var offset = range.index - quill.getIndex(line);

    quill.updateContents(
      new Delta()
        .retain(upperStart)
        .concat(moved)
        .retain(lowerStart - upperStart)
        .delete(lowerLength),
      "user"
    );

    var start = step < 0 ? upperStart : upperStart + lowerLength;

    quill.setSelection(start + offset, range.length, "user");
    quill.scrollSelectionIntoView();
  }

  /**
   * Where a block goes for `index`: at the end of a line's text, the
   * start of the next line, so that the line is not split and no empty
   * one is left behind - except on the last line, where an empty one
   * after the block is where the writer goes on.
   */
  function blockIndex(quill, index) {
    var found = quill.getLine(index);
    var line = found[0];

    if (line && found[1] === line.length() - 1 && index + 1 < quill.getLength()) {
      return index + 1;
    }

    return index;
  }

  /** Where in the text the point of a drop falls. */
  function indexAt(quill, event) {
    var native = null;

    if (document.caretRangeFromPoint) {
      native = document.caretRangeFromPoint(event.clientX, event.clientY);
    } else if (document.caretPositionFromPoint) {
      var position = document.caretPositionFromPoint(event.clientX, event.clientY);

      if (position) {
        native = document.createRange();
        native.setStart(position.offsetNode, position.offset);
        native.collapse(true);
      }
    }

    var normalized = native && quill.selection.normalizeNative(native);
    var range = normalized && quill.selection.normalizedToRange(normalized);

    if (range) {
      return range.index;
    }

    var selection = quill.getSelection();

    return selection ? selection.index : quill.getLength() - 1;
  }

  function readJson(id) {
    var element = document.getElementById(id);

    if (!element) {
      return null;
    }

    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      return null;
    }
  }

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

  /** The editor's HTML, as the server will store it. */
  function htmlOf(quill) {
    var html = quill.getSemanticHTML();

    // Spaces between words can come out as non-breaking ones, which
    // would stop the text wrapping; an empty editor still holds a <p>.
    html = html.replace(/(\S)&nbsp;(?=\S)/g, "$1 ");

    return html === "<p></p>" || html === "<p><br></p>" ? "" : html;
  }

  /** The first thing worth saying about a rejected request. */
  function errorText(error) {
    var data = error && (error.data || error.body || error.response);

    if (data && typeof data === "object") {
      if (data.detail) {
        return String(data.detail);
      }

      var first = Object.keys(data)[0];

      if (first) {
        var value = data[first];

        return first + ": " + (Array.isArray(value) ? value.join(" ") : String(value));
      }
    }

    return (error && error.message) || "";
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("wikiPage", function (configId) {
      var config = readJson(configId) || {};
      var quill = null;

      return {
        config: config,
        page: config.page,
        editing: false,
        saving: false,
        uploading: false,
        uploads: 0,
        dropping: false,
        filter: "",
        form: {},
        original: "",

        init: function () {
          var self = this;

          // A page just created opens straight in the editor.
          if (this.page && config.edit) {
            Generic.ready(function () {
              self.edit();
            });
          }

          window.addEventListener("beforeunload", function (event) {
            if (self.isDirty()) {
              event.preventDefault();
              event.returnValue = "";
            }
          });
        },

        matches: function (text) {
          var term = this.filter.trim().toLowerCase();

          return !term || String(text || "").indexOf(term) !== -1;
        },

        pageUrl: function (id) {
          return config.api + id + "/";
        },

        edit: function () {
          var self = this;
          var page = this.page;

          if (!window.Quill) {
            Generic.toast(t("The editor could not be loaded."), "error");
            return;
          }

          this.form = {
            title: page.title,
            slug: page.slug,
            parent: page.parent === null || page.parent === undefined ? "" : String(page.parent),
            position: page.position || 0,
            show_on_dashboard: Boolean(page.show_on_dashboard)
          };
          this.editing = true;

          this.$nextTick(function () {
            if (!quill) {
              quill = self.startEditor();
            }

            quill.setContents(
              quill.clipboard.convert({ html: page.content || "" }),
              "silent"
            );
            quill.history.clear();
            self.original = htmlOf(quill);
            quill.focus();
          });
        },

        startEditor: function () {
          var self = this;
          var toolbar = TOOLBAR.map(function (group) {
            // Without the upload endpoint, no file can be attached.
            return group.filter(function (name) {
              return name !== "attach" || config.filesUrl;
            });
          });

          registerFileBlock(window.Quill);

          var editor = new window.Quill(document.getElementById("wiki-editor"), {
            theme: "snow",
            placeholder: t("Write here\u2026"),
            modules: {
              toolbar: {
                container: toolbar,
                handlers: {
                  image: function () {
                    self.insertImage();
                  },
                  attach: function () {
                    self.chooseFiles();
                  },
                  moveUp: function () {
                    moveLine(editor, -1);
                  },
                  moveDown: function () {
                    moveLine(editor, 1);
                  }
                }
              },
              keyboard: {
                bindings: {
                  moveUp: {
                    key: "ArrowUp",
                    altKey: true,
                    handler: function () {
                      moveLine(editor, -1);
                      return false;
                    }
                  },
                  moveDown: {
                    key: "ArrowDown",
                    altKey: true,
                    handler: function () {
                      moveLine(editor, 1);
                      return false;
                    }
                  }
                }
              }
            }
          });

          Object.keys(BUTTONS).forEach(function (name) {
            var button = editor.getModule("toolbar").container.querySelector(".ql-" + name);

            if (button) {
              button.title = t(BUTTONS[name].label);
              button.setAttribute("aria-label", t(BUTTONS[name].label));
              button.appendChild(icon(BUTTONS[name].icon));
            }
          });

          this.acceptFiles(editor);

          return editor;
        },

        /**
         * Files dropped on the editor, or pasted into it, are uploaded
         * and put where they fell. Caught before Quill sees them: left
         * to it, an image would be inlined in the page as data, which
         * the server refuses, and any other file would be lost.
         */
        acceptFiles: function (editor) {
          var self = this;
          var container = editor.container;

          function hasFiles(event) {
            var types = event.dataTransfer && event.dataTransfer.types;

            return Boolean(types && Array.prototype.indexOf.call(types, "Files") !== -1);
          }

          container.addEventListener("dragover", function (event) {
            if (hasFiles(event)) {
              event.preventDefault();
              self.dropping = true;
            }
          });
          container.addEventListener("dragleave", function (event) {
            if (!container.contains(event.relatedTarget)) {
              self.dropping = false;
            }
          });
          container.addEventListener(
            "drop",
            function (event) {
              var files = event.dataTransfer && event.dataTransfer.files;

              self.dropping = false;

              if (!files || !files.length) {
                return;
              }

              event.preventDefault();
              event.stopPropagation();
              self.uploadFiles(Array.prototype.slice.call(files), indexAt(editor, event));
            },
            true
          );
          container.addEventListener(
            "paste",
            function (event) {
              var data = event.clipboardData;

              // A copied piece of a page carries its HTML: Quill's own.
              if (!data || !data.files || !data.files.length || data.getData("text/html")) {
                return;
              }

              event.preventDefault();
              event.stopPropagation();

              var range = editor.getSelection(true);

              self.uploadFiles(Array.prototype.slice.call(data.files), range ? range.index : undefined);
            },
            true
          );
        },

        /** The toolbar's paperclip: files from this computer. */
        chooseFiles: function () {
          var self = this;
          var input = el("input");

          input.type = "file";
          input.multiple = true;
          input.addEventListener("change", function () {
            if (input.files && input.files.length) {
              self.uploadFiles(Array.prototype.slice.call(input.files));
            }
          });
          input.click();
        },

        /**
         * Upload `files` one after the other, each put after the one
         * before, from `index` (the cursor when not given): images as
         * images, anything else as a file block.
         */
        uploadFiles: function (files, index) {
          var self = this;

          if (index === undefined) {
            var range = quill.getSelection(true);

            index = range ? range.index : quill.getLength() - 1;
          }

          files.reduce(function (previous, file) {
            return previous.then(function (at) {
              var isImage = config.imagesUrl && IMAGE_NAME.test(file.name || "");
              var sent = isImage ? self.uploadImage(file, at) : self.uploadFile(file, at);

              return sent.then(function (inserted) {
                return at + (inserted || 0);
              });
            });
          }, Promise.resolve(index));
        },

        /**
         * Send one file to the upload endpoint and put a block linking
         * to it at `index`. Resolves with the length inserted: 0 when it
         * was refused, which a toast says.
         */
        uploadFile: function (file, index) {
          var self = this;
          var limit = Number(config.imageMaxSize) || 0;

          if (!config.filesUrl) {
            Generic.toast(t("Only images can be added to this wiki."), "error");
            return Promise.resolve(0);
          }

          if (limit && file.size > limit) {
            Generic.toast(
              Generic.format(t("The file is too large: at most %(limit)s."), {
                limit: Generic.formatSize(limit)
              }),
              "error"
            );
            return Promise.resolve(0);
          }

          var body = new FormData();

          body.append("file", file, file.name);
          this.uploads += 1;
          this.uploading = true;

          return Generic.api
            .post(config.filesUrl, body)
            .then(function (data) {
              if (!data || !data.url) {
                throw new Error(t("The file could not be uploaded."));
              }

              var at = blockIndex(quill, index);
              var before = quill.getLength();

              quill.insertEmbed(at, "wikiFile", { url: data.url, name: data.name || file.name }, "user");

              // Past the block - and the line break a split may add.
              var next = at + quill.getLength() - before;

              quill.setSelection(next, 0, "user");

              return next - index;
            })
            .catch(function (error) {
              Generic.toast(errorText(error) || t("The file could not be uploaded."), "error");

              return 0;
            })
            .then(function (inserted) {
              self.uploads -= 1;
              self.uploading = self.uploads > 0;

              return inserted;
            });
        },

        /**
         * An image for the page: uploaded from this computer, or named
         * by its address. An upload comes back as an address under the
         * wiki, which only its readers may open; nothing is inlined in
         * the page. Without the upload endpoint, the address alone.
         */
        insertImage: function () {
          var self = this;

          if (!config.imagesUrl) {
            Generic.dialogs
              .prompt({
                title: t("Insert an image"),
                label: t("Address of the image"),
                placeholder: "https://"
              })
              .then(function (result) {
                self.embedImage(result && result.value);
              });
            return;
          }

          var dialog = Generic.dialogs.open({ title: t("Insert an image"), icon: "image" });
          var content = el("div", "stack");
          var upload = el("div", "sf-field");
          var chooser = el("label", "button button--primary sf-file__choose");
          var input = el("input", "sf-file__input");
          var form = el("form", "sf-field");
          var label = el("label", "sf-label", t("Or its address"));
          var address = el("input", "input");
          var cancel = el("button", "button button--ghost", t("Cancel"));
          var accept = el("button", "button", t("Insert"));
          var limit = Number(config.imageMaxSize) || 0;

          input.type = "file";
          input.accept = IMAGE_TYPES.join(",");
          chooser.append(icon("upload"), document.createTextNode(t("Upload an image")), input);
          upload.append(
            chooser,
            el(
              "p",
              "sf-help",
              limit
                ? Generic.format(t("PNG, JPEG, GIF or WebP, up to %(limit)s."), {
                    limit: Generic.formatSize(limit)
                  })
                : t("PNG, JPEG, GIF or WebP.")
            )
          );

          address.type = "text";
          address.id = "wiki-image-address";
          address.placeholder = "https://";
          label.htmlFor = address.id;
          form.append(label, address);
          content.append(upload, form);
          dialog.body.appendChild(content);

          cancel.type = "button";
          accept.type = "button";
          dialog.footer.append(cancel, accept);

          function byAddress(event) {
            if (event) {
              event.preventDefault();
            }

            if (!address.value.trim()) {
              address.focus();
              return;
            }

            dialog.close({ address: address.value });
          }

          input.addEventListener("change", function () {
            if (input.files && input.files[0]) {
              dialog.close({ file: input.files[0] });
            }
          });
          cancel.addEventListener("click", function () {
            dialog.close(null);
          });
          accept.addEventListener("click", byAddress);
          form.addEventListener("submit", byAddress);
          input.focus();

          dialog.closed.then(function (result) {
            if (result && result.file) {
              self.uploadImage(result.file);
            } else if (result && result.address) {
              self.embedImage(result.address);
            }
          });
        },

        /** Put the image at `url` where the cursor is; its length. */
        embedImage: function (value, index) {
          var url = value ? String(value).trim() : "";

          if (!url) {
            return 0;
          }

          if (!/^(https?:\/\/|\/)/i.test(url)) {
            Generic.toast(t("Give an address starting with https:// or /."), "error");
            return 0;
          }

          if (index === undefined) {
            var range = quill.getSelection(true);
            index = range ? range.index : quill.getLength();
          }

          quill.insertEmbed(index, "image", url, "user");
          quill.setSelection(index + 1, 0, "user");

          return 1;
        },

        /**
         * Send one image to the upload endpoint, and put what it answers
         * in the page, at `index` or the cursor. Checked here first - its
         * type, its size - and by the server again, from its bytes.
         * Resolves with the length inserted: 0 when it was refused.
         */
        uploadImage: function (file, index) {
          var self = this;
          var limit = Number(config.imageMaxSize) || 0;
          var type = String(file.type || "").toLowerCase();

          if (
            !IMAGE_NAME.test(file.name || "") ||
            (type && IMAGE_TYPES.indexOf(type) === -1)
          ) {
            Generic.toast(t("Only PNG, JPEG, GIF and WebP images can be added."), "error");
            return Promise.resolve(0);
          }

          if (limit && file.size > limit) {
            Generic.toast(
              Generic.format(t("The image is too large: at most %(limit)s."), {
                limit: Generic.formatSize(limit)
              }),
              "error"
            );
            return Promise.resolve(0);
          }

          if (index === undefined) {
            var range = quill.getSelection(true);

            index = range ? range.index : quill.getLength();
          }

          var body = new FormData();

          body.append("file", file, file.name);
          this.uploads += 1;
          this.uploading = true;

          return Generic.api
            .post(config.imagesUrl, body)
            .then(function (data) {
              if (!data || !data.url) {
                throw new Error(t("The image could not be uploaded."));
              }

              return self.embedImage(data.url, index);
            })
            .catch(function (error) {
              Generic.toast(errorText(error) || t("The image could not be uploaded."), "error");

              return 0;
            })
            .then(function (inserted) {
              self.uploads -= 1;
              self.uploading = self.uploads > 0;

              return inserted;
            });
        },

        isDirty: function () {
          if (!this.editing || !quill) {
            return false;
          }

          var page = this.page;
          var form = this.form;
          var parent = page.parent === null || page.parent === undefined ? "" : String(page.parent);

          return (
            htmlOf(quill) !== this.original ||
            form.title !== page.title ||
            form.slug !== page.slug ||
            String(form.parent) !== parent ||
            Number(form.position) !== Number(page.position) ||
            Boolean(form.show_on_dashboard) !== Boolean(page.show_on_dashboard)
          );
        },

        cancel: function () {
          var self = this;

          if (!this.isDirty()) {
            this.editing = false;
            return;
          }

          Generic.dialogs
            .confirm({
              title: t("Discard your changes?"),
              confirmLabel: t("Discard"),
              variant: "danger"
            })
            .then(function (confirmed) {
              if (confirmed) {
                self.editing = false;
              }
            });
        },

        save: function () {
          var self = this;
          var page = this.page;
          var form = this.form;

          if (!String(form.title || "").trim()) {
            Generic.toast(t("A page needs a title."), "error");
            return;
          }

          this.saving = true;

          Generic.api
            .patch(this.pageUrl(page.id), {
              title: String(form.title).trim(),
              slug: String(form.slug || "").trim(),
              parent: form.parent === "" ? null : Number(form.parent),
              position: Number(form.position) || 0,
              show_on_dashboard: Boolean(form.show_on_dashboard),
              content: htmlOf(quill),
              // Refused if someone saved in between.
              version: page.version
            })
            .then(function (data) {
              // The server draws the page, its menu and its address, and
              // the cleaned HTML is what the reader sees next.
              self.editing = false;
              Generic.flash(t("The page was saved."), "success");
              window.location.assign(data.url);
            })
            .catch(function (error) {
              Generic.toast(errorText(error) || t("The page could not be saved."), "error");
            })
            .then(function () {
              self.saving = false;
            });
        },

        create: function (parent) {
          Generic.dialogs
            .prompt({
              title: parent ? t("New subpage") : t("New page"),
              label: t("Title"),
              confirmLabel: t("Create")
            })
            .then(function (result) {
              var title = result && result.value ? String(result.value).trim() : "";

              if (!title) {
                return;
              }

              Generic.api
                .post(config.api, {
                  title: title,
                  wiki: config.wiki,
                  parent: parent || null,
                  content: ""
                })
                .then(function (data) {
                  window.location.assign(data.url + "?edit=1");
                })
                .catch(function (error) {
                  Generic.toast(errorText(error) || t("The page could not be created."), "error");
                });
            });
        },

        remove: function () {
          var self = this;
          var page = this.page;

          Generic.dialogs
            .confirm({
              title: t("Delete this page?"),
              message: Generic.format(
                t(
                  "\u201c%(title)s\u201d and its history will be deleted. " +
                    "Its subpages move up a level."
                ),
                { title: page.title }
              ),
              confirmLabel: t("Delete"),
              variant: "danger"
            })
            .then(function (confirmed) {
              if (!confirmed) {
                return;
              }

              Generic.api
                .delete(self.pageUrl(page.id))
                .then(function () {
                  Generic.flash(t("The page was deleted."), "success");
                  window.location.assign(config.indexUrl);
                })
                .catch(function (error) {
                  Generic.toast(errorText(error) || t("The page could not be deleted."), "error");
                });
            });
        },

        /** Earlier versions, newest first, each one restorable. */
        history: function () {
          var self = this;

          Generic.api
            .get(this.pageUrl(this.page.id) + "revisions/")
            .then(function (revisions) {
              var dialog = Generic.dialogs.open({ title: t("History"), icon: "history" });

              if (!revisions || !revisions.length) {
                dialog.body.appendChild(el("p", "", t("No earlier version yet.")));
              } else {
                var list = el("ul", "wiki-history");

                revisions.forEach(function (revision) {
                  var item = el("li", "wiki-history__item");
                  var text = el("div", "wiki-history__text");

                  text.appendChild(el("strong", "", revision.title));
                  text.appendChild(
                    el(
                      "span",
                      "wiki-history__meta",
                      Generic.format(t("%(date)s, by %(name)s - %(size)s characters"), {
                        date: new Date(revision.created_at).toLocaleString(),
                        name: revision.author_name || t("someone"),
                        size: revision.size
                      })
                    )
                  );
                  item.appendChild(text);

                  if (config.can && config.can.change) {
                    var restore = el("button", "button button--sm", t("Restore"));

                    restore.type = "button";
                    restore.addEventListener("click", function () {
                      dialog.close(false);
                      self.restore(revision);
                    });
                    item.appendChild(restore);
                  }

                  list.appendChild(item);
                });

                dialog.body.appendChild(list);
              }

              var close = el("button", "button button--ghost", t("Close"));

              close.type = "button";
              close.addEventListener("click", function () {
                dialog.close(false);
              });
              dialog.footer.appendChild(close);
            })
            .catch(function (error) {
              Generic.toast(errorText(error) || t("The history could not be loaded."), "error");
            });
        },

        restore: function (revision) {
          var self = this;

          Generic.dialogs
            .confirm({
              title: t("Restore this version?"),
              message: t("The current text goes to the history, so this can be undone."),
              confirmLabel: t("Restore")
            })
            .then(function (confirmed) {
              if (!confirmed) {
                return;
              }

              Generic.api
                .post(self.pageUrl(self.page.id) + "restore/", { revision: revision.id })
                .then(function (data) {
                  Generic.flash(t("The version was restored."), "success");
                  window.location.assign(data.url);
                })
                .catch(function (error) {
                  Generic.toast(errorText(error) || t("The version could not be restored."), "error");
                });
            });
        }
      };
    });

    /** The list of wikis: a new one, its name and description, deleting it. */
    window.Alpine.data("wikiList", function (configId) {
      var config = readJson(configId) || {};

      function find(id) {
        return (config.wikis || []).find(function (wiki) {
          return wiki.id === id;
        });
      }

      function ask(title, wiki, confirmLabel) {
        return Generic.dialogs.fields({
          title: title,
          icon: "auto_stories",
          confirmLabel: confirmLabel,
          fields: [
            { name: "name", label: t("Name"), value: wiki ? wiki.name : "", required: true, maxLength: 200 },
            { name: "description", label: t("Description"), value: wiki ? wiki.description : "", multiline: true }
          ]
        });
      }

      return {
        config: config,

        create: function () {
          ask(t("New wiki"), null, t("Create")).then(function (values) {
            if (!values) {
              return;
            }

            Generic.api
              .post(config.api, values)
              .then(function (data) {
                window.location.assign(data.url);
              })
              .catch(function (error) {
                Generic.toast(errorText(error) || t("The wiki could not be created."), "error");
              });
          });
        },

        edit: function (id) {
          var wiki = find(id);

          if (!wiki) {
            return;
          }

          ask(t("Edit the wiki"), wiki, t("Save")).then(function (values) {
            if (!values) {
              return;
            }

            Generic.api
              .patch(config.api + id + "/", values)
              .then(function () {
                Generic.flash(t("The wiki was saved."), "success");
                window.location.reload();
              })
              .catch(function (error) {
                Generic.toast(errorText(error) || t("The wiki could not be saved."), "error");
              });
          });
        },

        remove: function (id) {
          var wiki = find(id);

          if (!wiki) {
            return;
          }

          Generic.dialogs
            .confirm({
              title: t("Delete this wiki?"),
              message: Generic.format(
                t("\u201c%(name)s\u201d and its %(count)s pages, with their history, will be deleted."),
                { name: wiki.name, count: wiki.page_count }
              ),
              confirmLabel: t("Delete"),
              variant: "danger"
            })
            .then(function (confirmed) {
              if (!confirmed) {
                return;
              }

              Generic.api
                .delete(config.api + id + "/")
                .then(function () {
                  Generic.flash(t("The wiki was deleted."), "success");
                  window.location.reload();
                })
                .catch(function (error) {
                  Generic.toast(errorText(error) || t("The wiki could not be deleted."), "error");
                });
            });
        }
      };
    });
  });
})(window, document);

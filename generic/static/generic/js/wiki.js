/**
 * The wiki: a page, its editor, and the menu of pages.
 *
 * Reading needs nothing but the page itself. Editing starts Quill - a
 * rich-text editor - on the page's content and saves through the wiki
 * API as JSON. The server cleans the HTML before storing it and again
 * before showing it: the editor is a convenience, not a gatekeeper.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  var TOOLBAR = [
    [{ header: [2, 3, 4, false] }],
    ["bold", "italic", "underline", "strike", "code"],
    [{ list: "ordered" }, { list: "bullet" }, { indent: "-1" }, { indent: "+1" }],
    ["blockquote", "code-block", "link", "image"],
    [{ align: [] }],
    ["clean"]
  ];

  //: The images a page may hold, as the upload endpoint takes them.
  var IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  var IMAGE_NAME = /\.(png|jpe?g|gif|webp)$/i;

  function icon(name) {
    var node = el("span", "icon material-symbols-outlined", name);
    node.setAttribute("aria-hidden", "true");

    return node;
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
              quill = new window.Quill(document.getElementById("wiki-editor"), {
                theme: "snow",
                placeholder: t("Write here\u2026"),
                modules: {
                  toolbar: {
                    container: TOOLBAR,
                    handlers: {
                      image: function () {
                        self.insertImage();
                      }
                    }
                  }
                }
              });
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

        /** Put the image at `url` where the cursor is. */
        embedImage: function (value, index) {
          var url = value ? String(value).trim() : "";

          if (!url) {
            return;
          }

          if (!/^(https?:\/\/|\/)/i.test(url)) {
            Generic.toast(t("Give an address starting with https:// or /."), "error");
            return;
          }

          if (index === undefined) {
            var range = quill.getSelection(true);
            index = range ? range.index : quill.getLength();
          }

          quill.insertEmbed(index, "image", url, "user");
        },

        /**
         * Send one image to the upload endpoint, and put what it answers
         * in the page. Checked here first - its type, its size - and by
         * the server again, from its bytes.
         */
        uploadImage: function (file) {
          var self = this;
          var limit = Number(config.imageMaxSize) || 0;
          var type = String(file.type || "").toLowerCase();

          if (
            !IMAGE_NAME.test(file.name || "") ||
            (type && IMAGE_TYPES.indexOf(type) === -1)
          ) {
            Generic.toast(t("Only PNG, JPEG, GIF and WebP images can be added."), "error");
            return;
          }

          if (limit && file.size > limit) {
            Generic.toast(
              Generic.format(t("The image is too large: at most %(limit)s."), {
                limit: Generic.formatSize(limit)
              }),
              "error"
            );
            return;
          }

          var range = quill.getSelection(true);
          var index = range ? range.index : quill.getLength();
          var body = new FormData();

          body.append("file", file, file.name);
          this.uploading = true;

          Generic.api
            .post(config.imagesUrl, body)
            .then(function (data) {
              self.uploading = false;

              if (!data || !data.url) {
                throw new Error(t("The image could not be uploaded."));
              }

              self.embedImage(data.url, index);
            })
            .catch(function (error) {
              self.uploading = false;
              Generic.toast(errorText(error) || t("The image could not be uploaded."), "error");
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
                .post(config.api, { title: title, parent: parent || null, content: "" })
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
  });
})(window, document);

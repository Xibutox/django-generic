/**
 * The "Merge uploaded Word files" page (documents/upload_merge.py):
 * files chosen or dropped, put in order, sent with the template in one
 * POST. The answer is the merged file, saved by the browser, or {"detail"} said
 * on the page - the files stay chosen either way.
 */
(function (window, document) {
  "use strict";

  var WORD = /\.(docx|dotx)$/i;

  function readConfig(id) {
    var element = document.getElementById(id);

    try {
      return element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      return {};
    }
  }

  /* The page's sentences, translated by the server (config.texts): the
     framework's JavaScript catalog does not hold this project's. */
  var texts = {};

  function t(text) {
    return texts[text] || text;
  }

  /* The name the server gave the file, from its Content-Disposition. */
  function fileName(response, fallback) {
    var header = response.headers.get("Content-Disposition") || "";
    var encoded = /filename\*=utf-8''([^;]+)/i.exec(header);
    var plain = /filename="([^"]+)"/i.exec(header);

    try {
      if (encoded) {
        return decodeURIComponent(encoded[1]);
      }
    } catch (error) {
      // An odd header: the plain name, or ours.
    }

    return plain ? plain[1] : fallback;
  }

  function save(blob, name) {
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement("a");

    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      window.URL.revokeObjectURL(url);
    }, 1000);
  }

  document.addEventListener("alpine:init", function () {
    window.Alpine.data("uploadMerge", function (configId) {
      var config = readConfig(configId);
      var counter = 0;

      texts = config.texts || {};

      return {
        files: [],
        template: null,
        name: "",
        pageBreaks: true,
        over: false,
        busy: false,
        error: "",

        size: function (bytes) {
          return window.Generic.formatSize(bytes);
        },

        weight: function () {
          return this.files.reduce(function (sum, entry) {
            return sum + entry.file.size;
          }, this.template ? this.template.size : 0);
        },

        total: function () {
          if (!this.files.length) {
            return "";
          }

          return window.Generic.format(t("%(count)s file(s), %(size)s"), {
            count: this.files.length,
            size: this.size(this.weight())
          });
        },

        add: function (list) {
          var refused = [];
          var max = config.maxFiles || 50;

          this.error = "";

          Array.prototype.forEach.call(list || [], function (file) {
            if (!WORD.test(file.name)) {
              refused.push(file.name);
            } else if (this.files.length < max) {
              counter += 1;
              this.files.push({ id: counter, file: file });
            }
          }, this);

          if (refused.length) {
            this.error = window.Generic.format(
              t("Not a Word file (.docx or .dotx): %(names)s"),
              { names: refused.join(", ") }
            );
          } else if (this.files.length >= max && list && list.length) {
            this.error = window.Generic.format(
              t("At most %(count)s files can be merged at once."),
              { count: max }
            );
          }
        },

        drop: function (event) {
          this.over = false;
          this.add(event.dataTransfer ? event.dataTransfer.files : []);
        },

        setTemplate: function (list) {
          var file = list && list[0];

          this.error = "";

          if (file && !WORD.test(file.name)) {
            this.error = window.Generic.format(
              t("Not a Word file (.docx or .dotx): %(names)s"),
              { names: file.name }
            );
            return;
          }

          this.template = file || null;
        },

        move: function (index, step) {
          var target = index + step;

          if (target < 0 || target >= this.files.length) {
            return;
          }

          var entry = this.files.splice(index, 1)[0];

          this.files.splice(target, 0, entry);
        },

        remove: function (index) {
          this.files.splice(index, 1);
        },

        submit: function () {
          var self = this;
          var body = new FormData();

          if (!this.files.length || this.busy) {
            return;
          }

          if (config.maxSize && this.weight() > config.maxSize) {
            this.error = window.Generic.format(
              t("The files weigh more than %(size)s together."),
              { size: this.size(config.maxSize) }
            );
            return;
          }

          this.files.forEach(function (entry) {
            body.append("documents", entry.file, entry.file.name);
          });

          if (this.template) {
            body.append("template", this.template, this.template.name);
          }

          body.append("name", this.name);

          if (this.pageBreaks) {
            body.append("page_breaks", "on");
          }

          this.busy = true;
          this.error = "";

          window
            .fetch(config.url, {
              method: "POST",
              credentials: "same-origin",
              headers: {
                "X-CSRFToken": window.Generic.csrfToken(),
                "X-Requested-With": "XMLHttpRequest"
              },
              body: body
            })
            .then(function (response) {
              if (response.ok) {
                return response.blob().then(function (blob) {
                  save(blob, fileName(response, "merged.docx"));
                  window.Generic.toast(t("The merged file is ready."), "success");
                });
              }

              return response
                .json()
                .catch(function () {
                  return null;
                })
                .then(function (data) {
                  self.error = window.Generic.api.errorMessage(
                    data,
                    response.status
                  );
                });
            })
            .catch(function () {
              self.error = t("The request failed. Please try again.");
            })
            .then(function () {
              self.busy = false;
            });
        }
      };
    });
  });
})(window, document);

/**
 * The application frame: sidebar, navigation filter, messages, and the
 * Alpine components the top bar is made of.
 *
 * Alpine is used for what it is good at - small pieces of state bound
 * to markup: a menu open or closed, a list fetched as JSON and drawn
 * with x-for. Every list here comes from a DRF endpoint as JSON; no
 * HTML fragment is ever fetched from the server.
 *
 * The components register on `alpine:init`, which is why this file
 * loads before Alpine itself.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;

  /* -- Sidebar ---------------------------------------------------------
   *
   * Two states, remembered apart because they answer two questions:
   *
   *   open / closed   is it on screen now (the bar's own button)
   *   pinned / not    does it hold the page open, or float over it
   *
   * Unpinned, the page gets the whole width and the navigation becomes
   * a panel: the strip along the left edge opens it on hover and it
   * slides away when the pointer leaves, while the bar's button opens
   * it and holds it there until it is dismissed.
   *
   * Open and closed describe the pinned column only. Unpinned, the
   * panel is never hidden outright - it is parked outside the viewport,
   * because something has to be left for the edge to bring back.
   *
   * Both are applied to <html> inline in base.html before first paint;
   * this only changes them and remembers the choice. Two classes rather
   * than one for open, because the default differs by width: beside the
   * content on a wide screen, over it on a narrow one.
   */

  var SIDEBAR_KEY = "generic.sidebar";
  var PINNED_KEY = "generic.sidebar-pinned";
  var NARROW = "(max-width: 1024px)";

  //: How long the panel waits before sliding away, so crossing a corner
  //: on the way to it does not close it under the pointer.
  var PEEK_DELAY = 400;

  function initSidebar() {
    var buttons = document.querySelectorAll(".js-sidebar-toggle");
    var pins = document.querySelectorAll(".js-sidebar-pin");
    var edge = document.querySelector(".js-sidebar-edge");
    var sidebar = document.getElementById("sidebar");
    var root = document.documentElement;
    var timer = null;
    //: Opened by a click rather than by the pointer: it stays until it
    //: is dismissed, where a peek slides away on its own.
    var held = false;

    if (!buttons.length || !sidebar) {
      return;
    }

    function remember(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch (error) {
        /* Not being able to remember is survivable. */
      }
    }

    function narrow() {
      return window.matchMedia(NARROW).matches;
    }

    function pinned() {
      return !root.classList.contains("sidebar-unpinned");
    }

    // Below the breakpoint the navigation is already a panel the bar's
    // button opens over the page, so there is nothing left to unpin.
    function floating() {
      return !pinned() && !narrow();
    }

    function peeking() {
      return root.classList.contains("sidebar-peeking");
    }

    // On screen, not merely displayed: the floating panel is a whole
    // sidebar parked outside the viewport, and `display` calls it shown.
    function isVisible() {
      if (window.getComputedStyle(sidebar).display === "none") {
        return false;
      }

      return !floating() || peeking();
    }

    function sync() {
      var visible = isVisible();

      buttons.forEach(function (button) {
        if (button.tagName === "BUTTON") {
          button.setAttribute("aria-expanded", String(visible));
        }
      });

      pins.forEach(function (button) {
        var icon = button.querySelector(".js-sidebar-pin-icon");
        // The label names what the click will do, not the state.
        var label = pinned()
          ? button.getAttribute("data-label-unpin")
          : button.getAttribute("data-label-pin");

        button.setAttribute("aria-pressed", String(pinned()));
        button.classList.toggle("is-active", pinned());

        if (icon) {
          icon.textContent = pinned() ? "keep" : "keep_off";
        }

        if (label) {
          button.setAttribute("title", label);
          button.setAttribute("aria-label", label);
        }
      });
    }

    function apply(open) {
      if (floating()) {
        // Hiding the panel outright would strand it: the edge opens
        // what is parked outside the viewport, not what is display:none,
        // and the pin that brings it back travels with it.
        hold(open);
        return;
      }

      root.classList.toggle("sidebar-open", open);
      root.classList.toggle("sidebar-closed", !open);

      // Only the wide layout's choice is worth remembering: on a phone
      // the sidebar is a menu, opened and dismissed each time.
      if (!narrow()) {
        remember(SIDEBAR_KEY, open ? "open" : "closed");
      }

      sync();
    }

    /* Peeking: floating only. A pinned sidebar is already there. */

    function keepOpen() {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function closeLater() {
      if (timer !== null) {
        return;
      }

      timer = window.setTimeout(function () {
        timer = null;
        peek(false);
      }, PEEK_DELAY);
    }

    function peek(on) {
      keepOpen();

      if (!floating() || (held && !on)) {
        return;
      }

      root.classList.toggle("sidebar-peeking", on);
      sync();
    }

    function hold(on) {
      keepOpen();
      held = on;
      root.classList.toggle("sidebar-peeking", on && floating());
      sync();
    }

    function save(value) {
      var config = Generic.config();
      var url = config.api && config.api.preferences;

      if (!url || !config.user.authenticated) {
        return;
      }

      // Kept on the account as well, so the choice follows the user to
      // another browser. The class already applies; a failure here
      // costs the next machine, not this page.
      Generic.api
        .patch(url, { navigation: value ? "pinned" : "floating" })
        .catch(function () {});
    }

    function setPinned(value) {
      root.classList.toggle("sidebar-unpinned", !value);
      remember(PINNED_KEY, String(value));
      save(value);
      held = false;
      root.classList.remove("sidebar-peeking");

      if (value) {
        // Pinning brings it back: a pinned sidebar left closed would
        // give the pin nothing to act on.
        apply(true);
      }

      sync();
    }

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        apply(!isVisible());
      });
    });

    pins.forEach(function (button) {
      button.addEventListener("click", function () {
        setPinned(!pinned());
      });
    });

    if (edge) {
      edge.addEventListener("mouseenter", function () {
        peek(true);
      });
      edge.addEventListener("focus", function () {
        peek(true);
      });
      // A click pins it back: reaching for the edge twice means the
      // navigation is wanted, not a panel that keeps sliding away.
      edge.addEventListener("click", function () {
        setPinned(true);
      });
    }

    sidebar.addEventListener("mouseenter", function () {
      peek(true);
    });
    sidebar.addEventListener("mouseleave", function () {
      closeLater();
    });
    sidebar.addEventListener("focusin", function () {
      peek(true);
    });

    // What keeps the panel out is where the pointer is, not what it
    // entered. The panel slides out from under the strip to meet a
    // pointer that need not move again, and a browser only hit-tests on
    // a move: waiting for `mouseenter` on the panel closes it under a
    // pointer that is already on it.
    document.addEventListener("mousemove", function (event) {
      if (held || !peeking() || !floating()) {
        return;
      }

      // Where the panel is going, not where the slide has got to: half
      // way out, its measured edge would call a pointer waiting inside
      // it an outsider and close it again.
      if (event.clientX > sidebar.offsetWidth) {
        closeLater();
      } else {
        keepOpen();
      }
    });

    // A click anywhere else dismisses a panel opened from the bar. The
    // toggle and the strip handle their own clicks.
    document.addEventListener("click", function (event) {
      var target = event.target;

      if (!held || !target || !target.closest) {
        return;
      }

      if (
        sidebar.contains(target) ||
        target.closest(".js-sidebar-toggle, .js-sidebar-edge")
      ) {
        return;
      }

      hold(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }

      hold(false);

      if (narrow() && isVisible()) {
        apply(false);
      }
    });

    if (window.matchMedia) {
      window.matchMedia(NARROW).addEventListener("change", function () {
        // Crossing the breakpoint changes what the default is, so a
        // class left over from the other layout must not stick.
        held = false;
        root.classList.remove("sidebar-open", "sidebar-peeking");
        sync();
      });
    }

    sync();

    var current = sidebar.querySelector('[aria-current="page"]');

    if (current && current.scrollIntoView) {
      current.scrollIntoView({ block: "nearest" });
    }
  }

  /* -- Navigation filter ---------------------------------------------- */

  function initNavFilter() {
    var input = document.querySelector(".js-nav-filter");

    if (!input) {
      return;
    }

    var items = Array.from(document.querySelectorAll("[data-nav-item]"));
    var groups = Array.from(document.querySelectorAll("[data-nav-group]"));

    function apply() {
      var query = input.value.trim().toLowerCase();

      items.forEach(function (item) {
        item.hidden = Boolean(
          query && (item.dataset.navText || "").indexOf(query) === -1
        );
      });

      groups.forEach(function (group) {
        var visible = group.querySelector("[data-nav-item]:not([hidden])");
        group.hidden = !visible;

        if (query && visible && group.tagName === "DETAILS") {
          group.open = true;
        }
      });
    }

    input.addEventListener("input", apply);

    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        input.value = "";
        apply();
      } else if (event.key === "Enter") {
        var first = document.querySelector(
          "[data-nav-item]:not([hidden]) a"
        );

        if (first) {
          event.preventDefault();
          window.location.href = first.href;
        }
      }
    });
  }

  /* -- Flash messages ---------------------------------------------------
   *
   * Success and info messages fade out on their own; warnings and errors
   * stay until dismissed, because they usually describe something the
   * user still has to act on.
   */

  function initMessages() {
    document.querySelectorAll(".message").forEach(function (message) {
      var button = message.querySelector(".js-dismiss-message");

      if (button) {
        button.addEventListener("click", function () {
          message.remove();
        });
      }

      var level = message.dataset.messageLevel;

      if (level === "success" || level === "info") {
        window.setTimeout(function () {
          message.remove();
        }, 6000);
      }
    });
  }

  /* -- Alpine components ----------------------------------------------- */

  document.addEventListener("alpine:init", function () {
    var Alpine = window.Alpine;

    /** Light, dark, or whatever the operating system says. */
    Alpine.data("themeMenu", function () {
      var ICONS = { system: "contrast", light: "light_mode", dark: "dark_mode" };

      return {
        open: false,
        theme: Generic.theme.get(),

        get icon() {
          return ICONS[this.theme] || "contrast";
        },

        choose: function (value) {
          Generic.theme.set(value);
          this.theme = value;
          this.open = false;
        }
      };
    });

    /**
     * The appearance card: the theme, presets, and sliders over the
     * parameters every colour of the interface is computed from
     * (tokens.css). A change shows at once on the whole page;
     * Save keeps it on the account, where the next page renders it
     * before the first paint.
     *
     * Values are the stored integers, by preference name. A value equal
     * to the project's default is saved as empty, so the user follows
     * the project if its default changes later.
     */
    Alpine.data("appearanceEditor", function () {
      var names = Generic.appearance.names;

      var PRESETS = [
        { key: "standard", label: t("Standard"), values: {} },
        {
          key: "soft",
          label: t("Soft"),
          values: { contrast: -60, stripes: 35, colorfulness: 85 }
        },
        {
          key: "crisp",
          label: t("High contrast"),
          values: { contrast: 90, stripes: 100, tint: 0 }
        },
        { key: "vivid", label: t("Vivid"), values: { colorfulness: 125, tint: 80 } },
        { key: "neutral", label: t("Neutral"), values: { colorfulness: 0, tint: 0 } },
        { key: "ocean", label: t("Ocean"), values: { accent_hue: 220, tint: 60 } },
        { key: "forest", label: t("Forest"), values: { accent_hue: 150, tint: 55 } },
        { key: "amber", label: t("Amber"), values: { accent_hue: 60, tint: 55 } },
        { key: "rose", label: t("Rose"), values: { accent_hue: 355, tint: 50 } },
        { key: "violet", label: t("Violet"), values: { accent_hue: 295, tint: 60 } }
      ];

      function pick(source) {
        var result = {};

        names.forEach(function (name) {
          if (source && source[name] !== null && source[name] !== undefined) {
            result[name] = Number(source[name]);
          }
        });

        return result;
      }

      return {
        presets: PRESETS,
        themes: [
          { value: "system", label: t("System"), icon: "contrast" },
          { value: "light", label: t("Light"), icon: "light_mode" },
          { value: "dark", label: t("Dark"), icon: "dark_mode" }
        ],
        theme: Generic.theme.get(),
        defaults: {},
        saved: {},
        values: {},
        saving: false,

        init: function () {
          var self = this;
          var preferences = Generic.config().preferences || {};

          this.defaults = Generic.appearance.defaults();
          this.saved = pick(preferences.appearance);
          this.values = Object.assign({}, this.defaults, this.saved);

          // The theme menu in the top bar changes it too.
          document.addEventListener("generic:themechange", function (event) {
            self.theme = (event.detail && event.detail.theme) || "system";
          });
        },

        /** The user's own values: those that differ from the project's. */
        own: function () {
          var own = {};
          var self = this;

          names.forEach(function (name) {
            var value = Number(self.values[name]);

            own[name] = value === self.defaults[name] ? null : value;
          });

          return own;
        },

        get dirty() {
          var own = this.own();
          var saved = this.saved;

          return names.some(function (name) {
            var before = saved[name] === undefined ? null : saved[name];

            return own[name] !== before;
          });
        },

        preview: function () {
          Generic.appearance.apply(this.own());
        },

        usePreset: function (preset) {
          this.values = Object.assign({}, this.defaults, preset.values);
          this.preview();
        },

        /** The accent a preset would give, for its button. */
        swatch: function (preset) {
          var values = Object.assign({}, this.defaults, preset.values);
          var chroma = 0.19 * (values.colorfulness / 100);
          var lightness = 0.6 - 0.1 * (values.contrast / 100);

          return {
            background:
              "oklch(" + lightness + " " + chroma + " " + values.accent_hue + ")"
          };
        },

        reset: function () {
          this.values = Object.assign({}, this.defaults);
          this.preview();
        },

        cancel: function () {
          this.values = Object.assign({}, this.defaults, this.saved);
          this.preview();
        },

        setTheme: function (value) {
          Generic.theme.set(value);
          this.theme = value;
        },

        percent: function (name) {
          return Math.round(Number(this.values[name])) + "%";
        },

        signed: function (name) {
          var value = Math.round(Number(this.values[name]));

          return (value > 0 ? "+" : "") + value;
        },

        save: function () {
          var self = this;
          var url = Generic.config().api.preferences;

          if (!url || this.saving) {
            return;
          }

          this.saving = true;

          Generic.api
            .patch(url, this.own())
            .then(function (data) {
              self.saved = pick(data);
              Generic.toast(t("Appearance saved."), "success");
            })
            .catch(function () {
              Generic.toast(t("The appearance could not be saved."), "error");
            })
            .then(function () {
              self.saving = false;
            });
        }
      };
    });

    /**
     * The bell: an unread count kept current by the WebSocket, and the
     * latest notifications fetched from the API when opened.
     */
    Alpine.data("notificationBell", function () {
      var LEVEL_ICONS = { 1: "info", 2: "check_circle", 3: "warning", 4: "error" };
      var LEVEL_TOASTS = { 1: "info", 2: "success", 3: "warning", 4: "error" };

      function normalize(raw) {
        var createdAt = raw.createdAt || raw.created_at;
        var readAt = raw.readAt !== undefined ? raw.readAt : raw.read_at;

        return {
          id: raw.id,
          title: raw.title || "",
          body: raw.body || "",
          level: Number(raw.level) || 1,
          url: raw.url && Generic.isSafeUrl(raw.url) ? raw.url : "",
          isRead: raw.read === true || Boolean(readAt),
          timeLabel: Generic.relativeTime(createdAt)
        };
      }

      return {
        open: false,
        unread: 0,
        items: [],
        loading: false,
        loaded: false,

        init: function () {
          var self = this;

          this.endpoints = Generic.config().api;
          this.fetchCount();

          Generic.events.on("connection.ready", function (payload) {
            if (typeof payload.unread === "number") {
              self.unread = payload.unread;
            }
          });

          Generic.events.on("notification.created", function (payload) {
            self.unread += 1;

            if (self.loaded) {
              self.items.unshift(normalize(payload));
            }

            Generic.toast(payload.title, LEVEL_TOASTS[payload.level] || "info");
          });

          Generic.events.on("notification.updated", function (payload) {
            var updated = normalize(payload);

            self.items = self.items.map(function (item) {
              return item.id === updated.id ? updated : item;
            });
            self.fetchCount();
          });

          Generic.events.on("notification.deleted", function (payload) {
            self.items = self.items.filter(function (item) {
              return item.id !== payload.id;
            });
            self.fetchCount();
          });

          Generic.events.on("notification.read_all", function () {
            self.unread = 0;
            self.items.forEach(function (item) {
              item.isRead = true;
            });
          });

          // Without a socket - a WSGI server, a proxy that drops it -
          // the badge still catches up whenever the tab comes back.
          document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "visible") {
              self.fetchCount();
            }
          });
        },

        fetchCount: function () {
          var self = this;

          if (!this.endpoints.notificationsUnread) {
            return;
          }

          Generic.api
            .get(this.endpoints.notificationsUnread)
            .then(function (data) {
              self.unread = (data && data.unread) || 0;
            })
            .catch(function () {
              /* The badge simply stays as it was. */
            });
        },

        toggle: function () {
          this.open = !this.open;

          if (this.open) {
            this.load();
          }
        },

        load: function () {
          var self = this;

          this.loading = true;

          Generic.api
            .get(this.endpoints.notifications, { length: 8 })
            .then(function (data) {
              var rows = (data && (data.data || data.results)) ||
                (Array.isArray(data) ? data : []);

              self.items = rows.map(normalize);
              self.loaded = true;
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
            })
            .finally(function () {
              self.loading = false;
            });
        },

        detailUrl: function (id, action) {
          return (
            this.endpoints.notifications.replace(/\/?$/, "/") +
            encodeURIComponent(id) +
            "/" +
            action +
            "/"
          );
        },

        openItem: function (item, event) {
          if (!item.isRead) {
            item.isRead = true;
            this.unread = Math.max(0, this.unread - 1);
            Generic.api.post(this.detailUrl(item.id, "read"), {}).catch(
              function () {
                /* Marked read locally; the server catches up later. */
              }
            );
          }

          if (!item.url) {
            event.preventDefault();
          }
        },

        markAllRead: function () {
          var self = this;

          Generic.api
            .post(this.endpoints.notificationsReadAll, {})
            .then(function () {
              self.unread = 0;
              self.items.forEach(function (item) {
                item.isRead = true;
              });
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
            });
        },

        levelIcon: function (level) {
          return LEVEL_ICONS[level] || "info";
        }
      };
    });

    /**
     * Ctrl+K: search every page and record the user may see.
     *
     * Recent destinations are kept in this browser, the way an editor
     * remembers recently opened files.
     */
    Alpine.data("commandPalette", function () {
      var RECENT_KEY = "generic.palette.recent";

      return {
        open: false,
        term: "",
        loading: false,
        groups: [],
        flat: [],
        highlighted: 0,
        controller: null,

        show: function () {
          var self = this;

          this.open = true;
          this.term = "";
          this.showRecent();
          this.$nextTick(function () {
            self.$refs.input.focus();
          });
        },

        close: function () {
          this.open = false;

          if (this.controller) {
            this.controller.abort();
          }
        },

        shortcut: function (event) {
          var target = event.target;
          var typing =
            target &&
            (target.isContentEditable ||
              /^(input|textarea|select)$/i.test(target.tagName));

          if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();

            if (this.open) {
              this.close();
            } else {
              this.show();
            }
          } else if (!typing && !this.open && event.key === "/") {
            event.preventDefault();
            this.show();
          }
        },

        recent: function () {
          try {
            return JSON.parse(window.localStorage.getItem(RECENT_KEY)) || [];
          } catch (error) {
            return [];
          }
        },

        showRecent: function () {
          var items = this.recent();

          this.setGroups(
            items.length
              ? [{ label: t("Recent"), icon: "history", items: items }]
              : []
          );
        },

        setGroups: function (groups) {
          var index = 0;

          groups.forEach(function (group) {
            group.items.forEach(function (item) {
              item._index = index;
              index += 1;
            });
          });

          this.groups = groups;
          this.flat = groups.reduce(function (all, group) {
            return all.concat(group.items);
          }, []);
          this.highlighted = 0;
        },

        search: function () {
          var self = this;
          var term = this.term.trim();
          var url = Generic.config().urls.search;

          if (!term) {
            this.showRecent();
            return;
          }

          if (!url) {
            return;
          }

          if (this.controller) {
            this.controller.abort();
          }

          this.controller = new window.AbortController();
          this.loading = true;

          Generic.api
            .get(url, { q: term }, { signal: this.controller.signal })
            .then(function (data) {
              self.setGroups((data && data.groups) || []);
              self.loading = false;
            })
            .catch(function (error) {
              if (error && error.name === "AbortError") {
                return;
              }

              self.setGroups([]);
              self.loading = false;
            });
        },

        move: function (step) {
          if (!this.flat.length) {
            return;
          }

          this.highlighted =
            (this.highlighted + step + this.flat.length) % this.flat.length;

          var element = this.$refs.results.querySelector(
            '[data-index="' + this.highlighted + '"]'
          );

          if (element) {
            element.scrollIntoView({ block: "nearest" });
          }
        },

        go: function () {
          var item = this.flat[this.highlighted];

          if (!item || !Generic.isSafeUrl(item.url)) {
            return;
          }

          this.remember(item);
          window.location.href = item.url;
        },

        remember: function (item) {
          var list = this.recent().filter(function (entry) {
            return entry.url !== item.url;
          });

          list.unshift({
            label: item.label,
            url: item.url,
            icon: item.icon,
            description: item.description
          });

          try {
            window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 8)));
          } catch (error) {
            /* Not being able to remember is survivable. */
          }
        }
      };
    });

    /**
     * Watching: be told when this record changes, or when any record
     * of the model does.
     *
     *   <div x-data="watchControl" data-model="app.model"
     *        data-object-id="12" data-label="Ticket"
     *        data-label-plural="Tickets">
     *
     * Two watches, never one: a record and its model are separate
     * answers, and both are offered from a record's page. Without a
     * data-object-id - the button on a list page - there is only the
     * model, and the main button follows it.
     */
    Alpine.data("watchControl", function () {
      return {
        record: false,
        model: false,
        busy: false,
        open: false,
        modelName: "",
        objectId: "",

        init: function () {
          var self = this;
          var data = this.$el.dataset;
          var url = Generic.config().api.watchStatus;

          this.modelName = data.model || "";
          this.objectId = data.objectId || "";

          if (!url || !this.modelName) {
            return;
          }

          Generic.api
            .get(url, { model: this.modelName, objectId: this.objectId })
            .then(function (data) {
              self.record = Boolean(data && data.watching);
              self.model = Boolean(data && data.wholeModel);
            })
            .catch(function () {
              /* The button simply starts unwatched. */
            });
        },

        /** What the main button follows: the record, or the model. */
        get main() {
          return this.objectId ? this.record : this.model;
        },

        get label() {
          if (this.main) {
            return t("Watching");
          }

          return this.objectId ? t("Watch") : t("Watch every record");
        },

        get hint() {
          // The record is covered by the model's watch either way, and
          // a button saying nothing about that would look broken.
          if (this.objectId && this.model && !this.record) {
            return t("You are watching every record of this model.");
          }

          return this.label;
        },

        toggleMain: function () {
          if (this.objectId) {
            this.toggleRecord();
            return;
          }

          this.toggleModel();
        },

        toggleRecord: function () {
          this.send(this.objectId, "record");
        },

        toggleModel: function () {
          this.send("", "model");
        },

        send: function (objectId, which) {
          var self = this;
          var url = Generic.config().api.watchToggle;

          if (!url || this.busy) {
            return;
          }

          this.busy = true;

          Generic.api
            .post(url, { model: this.modelName, objectId: objectId })
            .then(function (data) {
              var on = Boolean(data && data.watching);

              self[which] = on;
              Generic.toast(
                on
                  ? t("You will be told about changes.")
                  : t("You will not be told any more."),
                "success"
              );
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
            })
            .finally(function () {
              self.busy = false;
            });
        }
      };
    });

    /**
     * The page's toolbar, on one line whatever it holds.
     *
     *   <div class="toolbar" x-data="pageToolbar">
     *     <a data-toolbar-slot="0" data-foldable>...</a>
     *     <div data-toolbar-more hidden>... <a data-toolbar-copy="0">
     *     <a data-toolbar-slot="1">Edit</a>
     *   </div>
     *
     * Every button is drawn by the server, in the bar and - when it may
     * fold - again in the menu. This only decides which of the two is
     * shown: the foldable buttons that do not fit go to the menu, from
     * the end of the list backwards, so the links a project put first
     * are the last to go, and the pinned ones never do.
     *
     * The room is the header's to give, not the buttons': the tools
     * are laid out from the least they need (pinned buttons, the menu's
     * button and whatever sits beside the toolbar) and grow into what
     * the title leaves. Folding never changes that width, so the bar
     * never folds, grows, and folds again.
     */
    Alpine.data("pageToolbar", function () {
      return {
        open: false,

        init: function () {
          var self = this;
          var root = this.$root;
          var fold = function () {
            self.fold();
          };
          var later = Generic.debounce(fold, 80);

          this.$nextTick(function () {
            fold();
            root.classList.add("is-measured");
          });

          // Icons are a font: until it arrives, "edit_note" is drawn as
          // the nine letters it is and every button is too wide.
          if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(fold);
          }

          if (!window.ResizeObserver) {
            window.addEventListener("resize", later);
            return;
          }

          // The header's width, and the width of what sits beside the
          // toolbar - the Watch button's label changes once it knows.
          var observer = new window.ResizeObserver(later);
          var parent = root.parentElement;

          if (parent) {
            observer.observe(parent);

            Array.prototype.forEach.call(parent.children, function (child) {
              if (child !== root) {
                observer.observe(child);
              }
            });
          }
        },

        fold: function () {
          var root = this.$root;
          var parent = root.parentElement;
          var more = root.querySelector(":scope > [data-toolbar-more]");
          var slots = root.querySelectorAll(":scope > [data-toolbar-slot]");
          var copies = root.querySelectorAll("[data-toolbar-copy]");

          if (!parent || !more) {
            return;
          }

          // Measured with every button shown, the menu's too. Nothing is
          // painted before the end of this function, so nothing flickers.
          Array.prototype.forEach.call(slots, function (slot) {
            slot.hidden = false;
          });
          more.hidden = false;

          var style = window.getComputedStyle(root);
          var gap = parseFloat(style.columnGap || style.gap) || 0;
          var outer = window.getComputedStyle(parent);
          var outerGap = parseFloat(outer.columnGap || outer.gap) || 0;
          var moreWidth = more.offsetWidth;
          var widths = [];
          var total = 0;
          var pinned = moreWidth;
          var beside = 0;

          Array.prototype.forEach.call(slots, function (slot, index) {
            var width = slot.offsetWidth;

            widths.push(width);
            total += width + (index ? gap : 0);

            if (!slot.hasAttribute("data-foldable")) {
              pinned += width + gap;
            }
          });

          Array.prototype.forEach.call(parent.children, function (child) {
            if (child !== root && child.offsetParent !== null) {
              beside += child.offsetWidth + outerGap;
            }
          });

          parent.style.setProperty(
            "--page-tools-basis",
            Math.ceil(beside + pinned) + "px"
          );

          // Read after the basis is set: this is the width the header
          // gives the tools, less what sits beside the toolbar.
          var room =
            parent.clientWidth -
            (parseFloat(outer.paddingLeft) || 0) -
            (parseFloat(outer.paddingRight) || 0) -
            beside;
          var menuOnly = root.querySelector("[data-menu-only]") !== null;
          var folded = {};
          var needed = total + (menuOnly ? gap + moreWidth : 0);

          if (needed > room) {
            needed = total + gap + moreWidth;

            for (var index = slots.length - 1; index >= 0; index--) {
              if (needed <= room) {
                break;
              }

              if (slots[index].hasAttribute("data-foldable")) {
                folded[slots[index].getAttribute("data-toolbar-slot")] = true;
                needed -= widths[index] + gap;
              }
            }
          }

          var inMenu = 0;

          Array.prototype.forEach.call(slots, function (slot) {
            slot.hidden = Boolean(folded[slot.getAttribute("data-toolbar-slot")]);
          });

          Array.prototype.forEach.call(copies, function (copy) {
            var shown =
              copy.hasAttribute("data-menu-only") ||
              Boolean(folded[copy.getAttribute("data-toolbar-copy")]);

            copy.hidden = !shown;
            inMenu += shown ? 1 : 0;
          });

          more.hidden = !inMenu;

          if (!inMenu) {
            this.open = false;
          }
        }
      };
    });

    /**
     * A DRF endpoint bound to markup: the "HTMX, but JSON" helper.
     *
     *   <div x-data="apiResource('/api/generic/watches/')">
     *     <template x-for="row in data" :key="row.id">
     *       <a :href="row.url" x-text="row.label"></a>
     *     </template>
     *   </div>
     *
     * The server returns data; the template decides how it looks.
     */
    Alpine.data("apiResource", function (url, params) {
      return {
        url: url,
        params: params || {},
        data: null,
        loading: false,
        error: "",

        init: function () {
          if (this.url) {
            this.load();
          }
        },

        load: function (extra) {
          var self = this;

          this.loading = true;
          this.error = "";

          return Generic.api
            .get(this.url, Object.assign({}, this.params, extra || {}))
            .then(function (data) {
              self.data = data;
              return data;
            })
            .catch(function (error) {
              self.error = error.message;
            })
            .finally(function () {
              self.loading = false;
            });
        },

        reload: function () {
          return this.load();
        },

        send: function (method, target, body) {
          var self = this;

          return Generic.api
            .request(method, target || this.url, { body: body })
            .then(function (result) {
              self.reload();
              return result;
            })
            .catch(function (error) {
              Generic.toast(error.message, "error");
              throw error;
            });
        }
      };
    });
  });

  Generic.ready(function () {
    initSidebar();
    initNavFilter();
    initMessages();
  });
})(window, document);

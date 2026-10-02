/**
 * The shared client toolkit: configuration, translation, the API
 * client, toasts and a few helpers.
 *
 * Every other script in the framework builds on `window.Generic`, which
 * is why this file loads first. It is deliberately small and has no
 * dependency: pages that never load jQuery or Alpine still get it.
 *
 * Non-ASCII characters are written as \uXXXX escapes, so the file
 * survives any editor or terminal encoding.
 */
(function (window, document) {
  "use strict";

  var Generic = (window.Generic = window.Generic || {});

  /* -- Configuration --------------------------------------------------
   *
   * base.html serialises the endpoints and the user into a JSON script
   * element; reading it rather than inline variables means no server
   * value is ever executed.
   */

  var configCache = null;

  function config() {
    if (configCache) {
      return configCache;
    }

    var element = document.getElementById("generic-config");

    try {
      configCache = element ? JSON.parse(element.textContent) : {};
    } catch (error) {
      configCache = {};
    }

    configCache.urls = configCache.urls || {};
    configCache.api = configCache.api || {};
    configCache.user = configCache.user || {};

    return configCache;
  }

  /* -- Translation ----------------------------------------------------
   *
   * Django's JavaScript catalog defines gettext globally when the page
   * loads it. Without it the English source string is used.
   */

  function t(text) {
    return typeof window.gettext === "function"
      ? window.gettext(text)
      : text;
  }

  function nt(singular, plural, count) {
    if (typeof window.ngettext === "function") {
      return window.ngettext(singular, plural, count);
    }

    return count === 1 ? singular : plural;
  }

  function format(text, values) {
    return String(text).replace(/%\((\w+)\)s/g, function (match, key) {
      return Object.prototype.hasOwnProperty.call(values, key)
        ? values[key]
        : match;
    });
  }

  /* -- Helpers --------------------------------------------------------- */

  function ready(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
    } else {
      callback();
    }
  }

  function debounce(callback, delay) {
    var timer;

    return function () {
      var args = arguments;
      var context = this;

      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        callback.apply(context, args);
      }, delay);
    };
  }

  function escapeHtml(value) {
    var node = document.createElement("div");
    node.textContent = value === null || value === undefined
      ? ""
      : String(value);

    return node.innerHTML;
  }

  function cookie(name) {
    var prefix = name + "=";
    var parts = document.cookie ? document.cookie.split(";") : [];

    for (var index = 0; index < parts.length; index += 1) {
      var part = parts[index].trim();

      if (part.indexOf(prefix) === 0) {
        return decodeURIComponent(part.slice(prefix.length));
      }
    }

    return null;
  }

  function csrfToken() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");

    return (
      cookie(config().csrfCookieName || "csrftoken") ||
      (input ? input.value : "") ||
      ""
    );
  }

  /**
   * Whether a URL is safe to put in an href.
   *
   * Escaping a URL does not make it safe: `javascript:alert(1)` is
   * valid HTML and runs on click. Only relative URLs and navigational
   * schemes pass.
   */
  function isSafeUrl(value) {
    var url = String(value || "").trim();

    if (/^[a-z][a-z0-9+.-]*:/i.test(url)) {
      return /^(https?|mailto|tel):/i.test(url);
    }

    return true;
  }

  function locale() {
    return document.documentElement.lang || undefined;
  }

  function formatDateTime(value) {
    if (!value) {
      return "";
    }

    var date = new Date(value);

    if (isNaN(date.getTime())) {
      return String(value);
    }

    return date.toLocaleString(locale(), {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  /**
   * A size in bytes, "12.3 KB", in the page's own language: 1024 bytes
   * to the kilobyte, as the server's messages count them.
   */
  function formatSize(bytes) {
    if (typeof bytes !== "number" || isNaN(bytes) || bytes < 0) {
      return "";
    }

    var units = ["byte", "kilobyte", "megabyte", "gigabyte"];
    var short = ["B", "KB", "MB", "GB"];
    var index = 0;
    var value = bytes;

    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }

    try {
      return new Intl.NumberFormat(locale(), {
        style: "unit",
        unit: units[index],
        // "12 bytes", "12 octets": the short form of a byte is no word.
        unitDisplay: index ? "short" : "long",
        maximumFractionDigits: index ? 1 : 0
      }).format(value);
    } catch (error) {
      return (index ? value.toFixed(1) : String(value)) + "\u00a0" + short[index];
    }
  }

  /** "5 minutes ago", in the page's own language. */
  function relativeTime(value) {
    if (!value) {
      return "";
    }

    var date = new Date(value);

    if (isNaN(date.getTime()) || typeof Intl.RelativeTimeFormat !== "function") {
      return formatDateTime(value);
    }

    var seconds = Math.round((date.getTime() - Date.now()) / 1000);
    var formatter = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
    var units = [
      ["year", 31536000],
      ["month", 2592000],
      ["week", 604800],
      ["day", 86400],
      ["hour", 3600],
      ["minute", 60]
    ];

    for (var index = 0; index < units.length; index += 1) {
      if (Math.abs(seconds) >= units[index][1]) {
        return formatter.format(
          Math.round(seconds / units[index][1]),
          units[index][0]
        );
      }
    }

    return formatter.format(seconds, "second");
  }

  /* -- API client ------------------------------------------------------
   *
   * Every call to the backend goes through here: same-origin cookies,
   * the CSRF header on anything that writes, JSON both ways, and one
   * error shape whatever went wrong.
   */

  function ApiError(message, status, data) {
    this.name = "ApiError";
    this.message = message;
    this.status = status;
    this.data = data;
  }

  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function buildUrl(url, params) {
    var target = new URL(url, window.location.origin);

    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];

      if (value === undefined || value === null || value === "") {
        return;
      }

      if (Array.isArray(value)) {
        target.searchParams.delete(key);
        value.forEach(function (item) {
          target.searchParams.append(key, item);
        });
      } else {
        target.searchParams.set(key, value);
      }
    });

    return target.toString();
  }

  /**
   * The most useful sentence a DRF error response contains.
   *
   * DRF answers with `{"detail": ...}`, `{"field": ["..."]}` or
   * `{"non_field_errors": [...]}`; the table endpoints with
   * `{"error": ...}`.
   */
  function errorMessage(data, status) {
    if (data && typeof data === "object") {
      if (typeof data.detail === "string") {
        return data.detail;
      }

      if (typeof data.error === "string") {
        return data.error;
      }

      var keys = Object.keys(data).filter(function (key) {
        return key.charAt(0) !== "_";
      });

      for (var index = 0; index < keys.length; index += 1) {
        var value = data[keys[index]];

        if (Array.isArray(value) && value.length && typeof value[0] === "string") {
          return keys[index] === "non_field_errors"
            ? value[0]
            : keys[index] + ": " + value[0];
        }

        if (typeof value === "string") {
          return value;
        }
      }
    }

    if (status === 403) {
      return t("You do not have permission to do that.");
    }

    if (status === 404) {
      return t("This record no longer exists.");
    }

    if (status >= 500) {
      return t("The server ran into a problem. Please try again.");
    }

    return format(t("The request failed (%(status)s)."), {
      status: status || "?"
    });
  }

  function request(method, url, options) {
    options = options || {};

    var headers = Object.assign(
      {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      options.headers || {}
    );

    var init = {
      method: method,
      credentials: "same-origin",
      headers: headers
    };

    if (method !== "GET" && method !== "HEAD") {
      headers["X-CSRFToken"] = csrfToken();
    }

    if (options.body !== undefined) {
      if (typeof FormData !== "undefined" && options.body instanceof FormData) {
        init.body = options.body;
      } else {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(options.body);
      }
    }

    if (options.signal) {
      init.signal = options.signal;
    }

    var target = options.params ? buildUrl(url, options.params) : url;

    return window.fetch(target, init).then(function (response) {
      if (response.status === 204) {
        return null;
      }

      return response
        .json()
        .catch(function () {
          return null;
        })
        .then(function (data) {
          if (!response.ok) {
            throw new ApiError(
              errorMessage(data, response.status),
              response.status,
              data
            );
          }

          return data;
        });
    });
  }

  /** The file name a Content-Disposition header gives, or "". */
  function dispositionName(header) {
    var encoded = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(header || "");

    if (encoded) {
      try {
        return decodeURIComponent(encoded[1].trim());
      } catch (error) {
        // Not percent-encoded after all: the plain name, if any.
      }
    }

    var plain = /filename="?([^";]+)"?/.exec(header || "");

    return plain ? plain[1].trim() : "";
  }

  /**
   * Send a request whose answer is a file, and save that file.
   *
   * For what a link cannot do: a POST, files of the reader's own in a
   * FormData. A refusal is read as JSON and thrown as an ApiError, like
   * every other call; the file is named as the server names it, else
   * fallbackName. Resolves with that name.
   */
  function download(url, body, options) {
    options = options || {};

    var init = {
      method: options.method || "POST",
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrfToken()
      }
    };

    if (body !== undefined) {
      if (typeof FormData !== "undefined" && body instanceof FormData) {
        init.body = body;
      } else {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
    }

    return window.fetch(url, init).then(function (response) {
      if (!response.ok) {
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (data) {
            throw new ApiError(
              errorMessage(data, response.status),
              response.status,
              data
            );
          });
      }

      var name =
        dispositionName(response.headers.get("Content-Disposition")) ||
        options.fallbackName ||
        "download";

      return response.blob().then(function (blob) {
        var link = document.createElement("a");
        var address = window.URL.createObjectURL(blob);

        link.href = address;
        link.download = name;
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
        // Revoked once the browser has started saving, not before.
        window.setTimeout(function () {
          window.URL.revokeObjectURL(address);
        }, 1000);

        return name;
      });
    });
  }

  var api = {
    request: request,
    download: download,
    buildUrl: buildUrl,
    errorMessage: errorMessage,
    ApiError: ApiError,
    get: function (url, params, options) {
      return request("GET", url, Object.assign({}, options, { params: params }));
    },
    post: function (url, body, options) {
      return request("POST", url, Object.assign({}, options, { body: body }));
    },
    patch: function (url, body, options) {
      return request("PATCH", url, Object.assign({}, options, { body: body }));
    },
    put: function (url, body, options) {
      return request("PUT", url, Object.assign({}, options, { body: body }));
    },
    delete: function (url, options) {
      return request("DELETE", url, options);
    }
  };

  /* -- Toasts ----------------------------------------------------------
   *
   * Feedback for something done without a page load: a row saved, an
   * action applied. Success and info fade on their own; a warning or an
   * error stays until dismissed, because it usually asks for action.
   */

  var TOAST_ICONS = {
    success: "check_circle",
    error: "error",
    warning: "warning",
    info: "info"
  };

  function toast(message, level, options) {
    level = TOAST_ICONS[level] ? level : "info";
    options = options || {};

    var region = document.getElementById("toasts");

    if (!region) {
      region = document.createElement("div");
      region.id = "toasts";
      region.className = "toasts";
      region.setAttribute("aria-live", "polite");
      document.body.appendChild(region);
    }

    var element = document.createElement("div");
    element.className = "toast toast--" + level;
    element.setAttribute("role", level === "error" ? "alert" : "status");

    var icon = document.createElement("span");
    icon.className = "icon material-symbols-outlined";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = TOAST_ICONS[level];

    var text = document.createElement("div");
    text.className = "toast__text";
    text.textContent = String(message || "");

    var close = document.createElement("button");
    close.type = "button";
    close.className = "icon-button icon-button--sm";
    close.setAttribute("aria-label", t("Dismiss"));
    close.innerHTML =
      '<span class="icon material-symbols-outlined icon--sm" ' +
      'aria-hidden="true">close</span>';

    function dismiss() {
      element.remove();
    }

    close.addEventListener("click", dismiss);
    element.append(icon, text, close);
    region.appendChild(element);

    var timeout = options.timeout !== undefined
      ? options.timeout
      : level === "success" || level === "info"
        ? 5000
        : 0;

    if (timeout) {
      window.setTimeout(dismiss, timeout);
    }

    return element;
  }

  /* -- Flash ------------------------------------------------------------
   *
   * A toast that survives one navigation: a form saves, then goes back
   * to the list, and the list is where "saved" should be read.
   */

  var FLASH_KEY = "generic.flash";

  function flash(message, level) {
    try {
      window.sessionStorage.setItem(
        FLASH_KEY,
        JSON.stringify({ message: String(message), level: level || "success" })
      );
    } catch (error) {
      /* Without storage the message is simply not carried over. */
    }
  }

  ready(function () {
    try {
      var raw = window.sessionStorage.getItem(FLASH_KEY);

      if (raw) {
        window.sessionStorage.removeItem(FLASH_KEY);

        var data = JSON.parse(raw);
        toast(data.message, data.level);
      }
    } catch (error) {
      /* A malformed entry is dropped with nothing to show. */
    }
  });

  /* -- Theme ------------------------------------------------------------ */

  var THEME_KEY = "generic.theme";

  var theme = {
    get: function () {
      try {
        var stored = window.localStorage.getItem(THEME_KEY);

        if (stored) {
          return stored;
        }
      } catch (error) {
        /* Private mode. */
      }

      return document.documentElement.dataset.themePreference || "system";
    },

    /** Show a theme and remember it in this browser only. */
    apply: function (value) {
      var root = document.documentElement;

      if (value === "light" || value === "dark") {
        root.dataset.theme = value;
      } else {
        delete root.dataset.theme;
        value = "system";
      }

      try {
        window.localStorage.setItem(THEME_KEY, value);
      } catch (error) {
        /* Not being able to remember is survivable. */
      }

      document.dispatchEvent(
        new CustomEvent("generic:themechange", { detail: { theme: value } })
      );

      return value;
    },

    /** Show a theme, and save it on the account as well. */
    set: function (value) {
      value = theme.apply(value);

      // Remembered on the account too, so the choice follows the user
      // to another browser.
      var url = config().api.preferences;

      if (url && config().user.authenticated) {
        api.patch(url, { theme: value }).catch(function () {
          /* The local choice already applies; nothing to report. */
        });
      }

      document.dispatchEvent(
        new CustomEvent("generic:themechange", { detail: { theme: value } })
      );
    }
  };

  /* -- Appearance --------------------------------------------------------- */

  /*
   * The parameters every colour of the interface is computed from
   * (tokens.css), by the name of the preference holding each one, with
   * the divisor from the stored integer to the CSS number.
   */
  var APPEARANCE = {
    accent_hue: { property: "--ui-hue", scale: 1 },
    colorfulness: { property: "--ui-colorfulness", scale: 100 },
    tint: { property: "--ui-tint", scale: 100 },
    contrast: { property: "--ui-contrast", scale: 100 },
    stripes: { property: "--ui-stripes", scale: 100 }
  };

  var appearance = {
    names: Object.keys(APPEARANCE),

    /**
     * The values in force without the user's own: the project's
     * defaults, as the stored integers. Read with the user's inline
     * values set aside for a moment, in one synchronous pass.
     */
    defaults: function () {
      var root = document.documentElement;
      var own = {};
      var values = {};

      appearance.names.forEach(function (name) {
        var property = APPEARANCE[name].property;

        own[name] = root.style.getPropertyValue(property);
        root.style.removeProperty(property);
      });

      var style = window.getComputedStyle(root);

      appearance.names.forEach(function (name) {
        var entry = APPEARANCE[name];
        var number = parseFloat(style.getPropertyValue(entry.property));

        values[name] = isNaN(number) ? 0 : Math.round(number * entry.scale);

        if (own[name]) {
          root.style.setProperty(entry.property, own[name]);
        }
      });

      return values;
    },

    /**
     * Show `values`, keyed by preference name. A null or missing one
     * follows the project's default.
     */
    apply: function (values) {
      var root = document.documentElement;

      appearance.names.forEach(function (name) {
        var entry = APPEARANCE[name];
        var value = values ? values[name] : null;

        if (value === null || value === undefined || value === "") {
          root.style.removeProperty(entry.property);
        } else {
          root.style.setProperty(
            entry.property,
            String(Number(value) / entry.scale)
          );
        }
      });

      document.dispatchEvent(
        new CustomEvent("generic:appearancechange", {
          detail: { values: values || {} }
        })
      );
    }
  };

  /* -- Colours ------------------------------------------------------------
   *
   * Colours that come from data - a tag's, a chart series' - end up in
   * a style attribute. They are checked against the same pattern the
   * server uses (generic/api/tags.py), and resolved to RGB through a
   * canvas, which understands every syntax the browser does.
   */

  var COLOR_PATTERN = new RegExp(
    "^(?:#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})" +
      "|[a-z]{3,30}" +
      "|(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\\([0-9a-z .,%/+-]{1,80}\\))$",
    "i"
  );

  var colorCanvas = null;
  var colorCache = {};

  var colors = {
    /** `value` when it is a plain CSS colour, "" otherwise. */
    clean: function (value) {
      var text = value === null || value === undefined ? "" : String(value).trim();

      return COLOR_PATTERN.test(text) ? text : "";
    },

    /** `[r, g, b, alpha]` for any colour the browser can paint. */
    rgb: function (value) {
      var key = String(value);

      if (colorCache[key]) {
        return colorCache[key];
      }

      if (!colorCanvas) {
        colorCanvas = document.createElement("canvas");
        colorCanvas.width = 1;
        colorCanvas.height = 1;
      }

      var context = colorCanvas.getContext("2d", { willReadFrequently: true });

      if (!context) {
        return [0, 0, 0, 1];
      }

      context.clearRect(0, 0, 1, 1);
      context.fillStyle = "#000";
      context.fillStyle = key;
      context.fillRect(0, 0, 1, 1);

      var data = context.getImageData(0, 0, 1, 1).data;
      var result = [data[0], data[1], data[2], data[3] / 255];

      colorCache[key] = result;

      return result;
    },

    /** A CSS value - a custom property included - as `rgb(r, g, b)`. */
    resolve: function (css, fallback) {
      var probe = document.createElement("span");

      probe.style.display = "none";
      probe.style.color = css;
      document.body.appendChild(probe);

      var computed = window.getComputedStyle(probe).color;

      probe.remove();

      if (!computed) {
        return fallback || "rgb(0, 0, 0)";
      }

      var channels = colors.rgb(computed);

      return (
        "rgba(" +
        channels[0] + ", " + channels[1] + ", " + channels[2] + ", " +
        channels[3] +
        ")"
      );
    },

    /** Relative luminance, WCAG's definition. */
    luminance: function (value) {
      var channels = colors.rgb(value).slice(0, 3).map(function (channel) {
        var c = channel / 255;

        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      });

      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    },

    /** Dark or light text, whichever reads better on `background`. */
    readableOn: function (background) {
      var light = colors.luminance(background);
      // Contrast against white, and against the near-black used below.
      var againstWhite = 1.05 / (light + 0.05);
      var againstDark = (light + 0.05) / 0.0588;

      return againstWhite >= againstDark ? "#ffffff" : "#111827";
    }
  };

  Object.assign(Generic, {
    appearance: appearance,
    api: api,
    colors: colors,
    config: config,
    cookie: cookie,
    csrfToken: csrfToken,
    debounce: debounce,
    escapeHtml: escapeHtml,
    flash: flash,
    format: format,
    formatDateTime: formatDateTime,
    formatSize: formatSize,
    isSafeUrl: isSafeUrl,
    nt: nt,
    ready: ready,
    relativeTime: relativeTime,
    t: t,
    theme: theme,
    toast: toast
  });
})(window, document);

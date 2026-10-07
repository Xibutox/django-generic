/**
 * The dashboard's key figures and record cards (generic.sites.dashboard).
 *
 * The page draws each tile and each set of cards without its data;
 * this asks each declaration's endpoint for it, and asks again when a
 * record of its resource changes (the resource's live topic).
 *
 *   <a class="kpi" data-kpi-url="..." data-resource="app.model"
 *      data-topic="resource.app.model">... [data-kpi-value] ...</a>
 *   <section class="record-cards" data-cards-url="...">
 *     ... [data-cards-grid] ...
 *   </section>
 *
 * Every value reaches the page through textContent (Generic.values),
 * every address through Generic.isSafeUrl.
 */
(function (window, document) {
  "use strict";

  var Generic = window.Generic;
  var t = Generic.t;
  var values = Generic.values;
  var el = values.el;

  var LEVELS = ["good", "warning", "danger"];

  /* -- Key figures -------------------------------------------------------- */

  function loadKpi(tile) {
    var output = tile.querySelector("[data-kpi-value]");
    var unit = tile.querySelector("[data-kpi-unit]");

    return Generic.api
      .get(tile.getAttribute("data-kpi-url"))
      .then(function (answer) {
        output.textContent = answer.display;
        unit.textContent = answer.unit || "";
        LEVELS.forEach(function (level) {
          tile.classList.toggle("kpi--" + level, answer.level === level);
        });
      })
      .catch(function () {
        output.textContent = "\u2014";
        tile.classList.add("kpi--failed");
      });
  }

  /* -- Cards ---------------------------------------------------------------- */

  function card(item) {
    var element = el("article", "record-card");
    var body = el("div", "record-card__body");
    var title = el("h3", "record-card__label");

    if (item.image && Generic.isSafeUrl(item.image)) {
      var picture = el("img", "record-card__image");

      picture.src = item.image;
      picture.alt = "";
      picture.loading = "lazy";
      element.appendChild(picture);
    }

    title.appendChild(values.link(item.url, item.label));
    body.appendChild(title);

    if (item.subtitle && !item.subtitle.empty) {
      var subtitle = el("div", "record-card__subtitle");

      subtitle.appendChild(values.render(item.subtitle));
      body.appendChild(subtitle);
    }

    if ((item.cells || []).length) {
      var list = el("dl", "record-card__values");

      item.cells.forEach(function (entry) {
        var row = el("div", "record-card__value");
        var value = el("dd");

        value.appendChild(values.render(entry));
        row.appendChild(el("dt", "", entry.label));
        row.appendChild(value);
        list.appendChild(row);
      });
      body.appendChild(list);
    }

    element.appendChild(body);

    // The whole card opens the record; the links inside it stay links.
    if (item.url && Generic.isSafeUrl(item.url)) {
      element.classList.add("record-card--link");
      element.addEventListener("click", function (event) {
        if (event.target.closest("a") || (window.getSelection && String(window.getSelection()))) {
          return;
        }

        window.location.href = item.url;
      });
    }

    return element;
  }

  function loadCards(section) {
    var grid = section.querySelector("[data-cards-grid]");
    var count = section.querySelector("[data-cards-count]");

    return Generic.api
      .get(section.getAttribute("data-cards-url"))
      .then(function (answer) {
        var items = answer.items || [];

        grid.textContent = "";
        grid.removeAttribute("aria-busy");

        if (!items.length) {
          grid.appendChild(el("p", "record-cards__empty muted", t("Nothing to show.")));
        }

        items.forEach(function (item) {
          grid.appendChild(card(item));
        });

        if (count) {
          count.textContent = String(answer.total);
          count.hidden = !answer.total;
        }
      })
      .catch(function () {
        grid.textContent = "";
        grid.removeAttribute("aria-busy");
        grid.appendChild(el("p", "record-cards__empty muted", t("These records could not be loaded.")));
      });
  }

  /* -- Live --------------------------------------------------------------- */

  function follow(elements, load) {
    if (!Generic.events) {
      return;
    }

    var byResource = {};

    elements.forEach(function (element) {
      var resource = element.getAttribute("data-resource");
      var topic = element.getAttribute("data-topic");

      if (!resource || !topic) {
        return;
      }

      if (!byResource[resource]) {
        byResource[resource] = [];
        Generic.events.subscribe(topic);
      }

      byResource[resource].push(element);
    });

    var pending = {};
    var reload = Generic.debounce(function () {
      Object.keys(pending).forEach(function (resource) {
        (byResource[resource] || []).forEach(load);
      });
      pending = {};
    }, 800);

    Generic.events.on("resource.changed", function (payload) {
      var resource = payload && payload.resource;

      if (resource && byResource[resource]) {
        pending[resource] = true;
        reload();
      }
    });
  }

  function start() {
    var tiles = Array.prototype.slice.call(document.querySelectorAll(".kpi[data-kpi-url]"));
    var sections = Array.prototype.slice.call(document.querySelectorAll(".record-cards[data-cards-url]"));

    tiles.forEach(loadKpi);
    sections.forEach(loadCards);
    follow(tiles, loadKpi);
    follow(sections, loadCards);
  }

  Generic.dashboard = { loadKpi: loadKpi, loadCards: loadCards };

  Generic.ready(start);
})(window, document);

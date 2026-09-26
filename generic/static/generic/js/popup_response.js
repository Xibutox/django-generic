/**
 * Runs inside the popup after a related object was saved.
 *
 * Hands the result to the window that opened it and closes. The payload
 * is read from a json_script element rather than an inline literal, so
 * no server value is ever interpolated into executable code.
 */
(function () {
  "use strict";

  var element = document.getElementById("popup-response-data");

  if (!element || !window.opener) {
    return;
  }

  var data;

  try {
    data = JSON.parse(element.textContent);
  } catch (error) {
    window.close();
    return;
  }

  window.opener.dispatchEvent(
    new CustomEvent("generic:popupresponse", { detail: data })
  );

  window.close();
})();

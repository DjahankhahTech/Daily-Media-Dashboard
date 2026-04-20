// Lightweight enhancement layer — the UI is fully functional without JS.
(function () {
  // Submit the filter bar on any change so analysts don't need to click Apply.
  document.querySelectorAll('form.filters').forEach(function (f) {
    f.querySelectorAll('select, input[type=date]').forEach(function (el) {
      el.addEventListener('change', function () { f.submit(); });
    });
  });

  // Give long-running actions (Assess) visible feedback while the POST is
  // in flight: disable the button and swap the label so the analyst knows
  // the click registered and doesn't double-submit.
  document.querySelectorAll('form.js-busy-form').forEach(function (f) {
    f.addEventListener('submit', function () {
      f.querySelectorAll('button[type=submit]').forEach(function (b) {
        var busy = b.getAttribute('data-busy-label');
        if (busy) { b.textContent = busy; }
        b.disabled = true;
        b.style.opacity = '0.7';
        b.style.cursor = 'wait';
      });
    });
  });
})();

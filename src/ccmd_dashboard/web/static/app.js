// Lightweight enhancement layer — the UI is fully functional without JS.
(function () {
  // Submit the filter bar on any change so analysts don't need to click Apply.
  document.querySelectorAll('form.filters').forEach(function (f) {
    f.querySelectorAll('select, input[type=date]').forEach(function (el) {
      el.addEventListener('change', function () { f.submit(); });
    });
  });
})();

(function () {
  document.querySelectorAll(".flag-category-head").forEach(function (heading) {
    heading.addEventListener("click", function () {
      heading.classList.toggle("collapsed");
      var list = heading.nextElementSibling;
      if (list) {
        list.classList.toggle("collapsed");
      }
    });
  });

  document.querySelectorAll(".kpi-flag-row[data-href]").forEach(function (row) {
    row.addEventListener("click", function () {
      var href = row.getAttribute("data-href");
      if (href) {
        window.location.href = href;
      }
    });
  });
})();

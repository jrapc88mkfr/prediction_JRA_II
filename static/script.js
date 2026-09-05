// 3ハロンVII - race.html 用スクリプト（並び替え + 一覧⇔詳細の画面切替）
(function () {
  var listEl = document.getElementById('screen-list');
  var detailEl = document.getElementById('screen-detail');
  var horseList = document.querySelector('.horse-list');
  if (!listEl || !horseList) return;

  // ---- 並び替え：単一ボタンで 馬番順→オッズ順→指数順 を循環 ----
  var modes = ['no', 'odds', 'index'];
  var labels = { no: '馬番順', odds: 'オッズ順', index: '指数順' };
  var sortBtn = document.getElementById('sort-btn');

  function sortBy(key) {
    var rows = Array.from(horseList.querySelectorAll('.grid-row'));
    rows.sort(function (a, b) {
      var av = parseFloat(a.dataset[key]);
      var bv = parseFloat(b.dataset[key]);
      if (key === 'index') return bv - av; // 指数は高い順
      return av - bv;                      // 馬番・オッズは低い順
    });
    rows.forEach(function (r, i) {
      r.classList.remove('h-odd', 'h-even');
      r.classList.add(i % 2 === 0 ? 'h-odd' : 'h-even');
      horseList.appendChild(r);
    });
  }

  if (sortBtn) {
    sortBtn.addEventListener('click', function () {
      var cur = modes.indexOf(sortBtn.dataset.mode);
      var next = modes[(cur + 1) % modes.length];
      sortBtn.dataset.mode = next;
      sortBtn.textContent = labels[next];
      sortBy(next);
    });
  }

  // ---- 一覧 ⇔ 詳細 画面切替 ----
  window.showDetail = function (no) {
    var target = document.getElementById('detail-' + no);
    if (!target) return;
    document.querySelectorAll('.detail-screen').forEach(function (d) {
      d.classList.add('hidden');
    });
    target.classList.remove('hidden');
    listEl.classList.add('hidden');
    detailEl.classList.remove('hidden');
    window.scrollTo(0, 0);
  };

  window.showList = function () {
    detailEl.classList.add('hidden');
    listEl.classList.remove('hidden');
    window.scrollTo(0, 0);
  };
})();

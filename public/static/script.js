// 3ハロンVII - race.html 用スクリプト（並び替え + 一覧⇔詳細の画面切替）
(function () {
  var listEl = document.getElementById('screen-list');
  var detailEl = document.getElementById('screen-detail');

  // ---- 並び替え：単一ボタンで 馬番順→オッズ順→指数順 を循環 ----
  var cardList = document.querySelector('.horse-cards');
  var modes = ['no', 'odds', 'index'];
  var labels = { no: '馬番順', odds: 'オッズ順', index: '指数順' };
  var sortBtn = document.getElementById('sort-btn');

  function sortBy(key) {
    if (!cardList) return;
    var cards = Array.from(cardList.querySelectorAll('.h-card'));
    cards.sort(function (a, b) {
      var av = parseFloat(a.dataset[key]);
      var bv = parseFloat(b.dataset[key]);
      if (key === 'index') return bv - av; // 指数は高い順
      return av - bv;                      // 馬番・オッズは低い順
    });
    cards.forEach(function (c, i) {
      c.classList.remove('h-odd', 'h-even');
      c.classList.add(i % 2 === 0 ? 'h-odd' : 'h-even');
      cardList.appendChild(c);
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
    if (!target || !listEl || !detailEl) return;
    document.querySelectorAll('.detail-screen').forEach(function (d) {
      d.classList.add('hidden');
    });
    target.classList.remove('hidden');
    listEl.classList.add('hidden');
    detailEl.classList.remove('hidden');
    window.scrollTo(0, 0);
  };

  window.showList = function () {
    if (!listEl || !detailEl) return;
    detailEl.classList.add('hidden');
    listEl.classList.remove('hidden');
    window.scrollTo(0, 0);
  };
})();

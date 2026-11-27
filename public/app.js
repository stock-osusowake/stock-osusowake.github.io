(function () {
  'use strict';

  var container = document.getElementById('products');

  // 日本時間 (Asia/Tokyo) の今日の日付 YYYY-MM-DD
  function todayJst() {
    var parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date());
    var m = {};
    parts.forEach(function (p) { m[p.type] = p.value; });
    return m.year + '-' + m.month + '-' + m.day;
  }

  // No. は products.json の no（固定番号）。期限切れで消えても番号はずれない
  // active が true で、until を過ぎていないものだけ（until 当日までは表示）
  function isVisible(p, today) {
    if (!p || p.active !== true) return false;
    if (p.until && today > p.until) return false;
    return true;
  }

  function el(tag, className, text) {
    var e = document.createElement(tag);
    if (className) e.className = className;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function renderCard(p, no) {
    var card = el('article', 'card');
    var head = el('div', 'card-head');
    head.appendChild(el('span', 'card-no', 'No.' + no));
    if (p.label) head.appendChild(el('span', 'card-label', p.label));
    card.appendChild(head);
    card.appendChild(el('h2', null, p.name));
    card.appendChild(el('p', 'card-desc', p.description));

    if (typeof p.url === 'string' && p.url.indexOf('https://') === 0) {
      var a = el('a', 'btn', 'Amazonで見る');
      a.href = p.url;
      a.target = '_blank';
      a.rel = 'sponsored noopener noreferrer';
      a.setAttribute('aria-label', 'Amazonで見る：' + p.name);
      card.appendChild(a);
    }
    return card;
  }

  function showMessage(text) {
    container.textContent = '';
    container.appendChild(el('p', 'status', text));
  }

  function render(data) {
    var today = todayJst();
    var items = (data.products || []).filter(function (p) { return isVisible(p, today); });
    if (items.length === 0) {
      showMessage('いま紹介中の商品はありません。次の動画をおたのしみに。');
      return;
    }
    container.textContent = '';
    items.forEach(function (p) { container.appendChild(renderCard(p, p.no)); });
  }

  fetch('/products.json', { cache: 'no-cache' })
    .then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(render)
    .catch(function () {
      showMessage('商品一覧を読み込めませんでした。時間をおいてもう一度お試しください。');
    });
})();

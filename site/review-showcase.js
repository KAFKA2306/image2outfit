(() => {
  'use strict';

  const data = window.REVIEW_CONSOLE_DATA;
  if (!data || !Array.isArray(data.products)) return;

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
  const safeHref = (value) => {
    const href = String(value || '').trim();
    return href && !href.toLowerCase().startsWith('javascript:') ? esc(href) : '';
  };
  const stateLabel = (state) => ({
    RELEASED: '公開準備済み',
    TECHNICAL_READY: '技術確認済み',
    HUMAN_REVIEW_PENDING: 'レビュー待ち',
    WORKING: '制作中',
    REJECTED: '要修正'
  })[state] || state || '状態不明';
  const prettySlug = (slug) => String(slug || '')
    .split('-')
    .filter(Boolean)
    .map((part) => part.length <= 3 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1))
    .join(' ');
  const formatDate = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || '不明');
    return new Intl.DateTimeFormat('ja-JP', { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
  };
  const imageAssets = (product) => (product?.assets || []).filter((asset) => asset.href);
  const orderedImages = (product) => {
    const priority = ['front', 'three-quarter', 'back', 'left', 'right'];
    return imageAssets(product).slice().sort((a, b) => {
      const ai = priority.indexOf(a.name);
      const bi = priority.indexOf(b.name);
      const av = ai === -1 ? 999 : ai;
      const bv = bi === -1 ? 999 : bi;
      return av - bv || String(a.name).localeCompare(String(b.name));
    });
  };

  const params = new URLSearchParams(location.search);
  const requestedSlug = params.get('product');
  let product = data.products.find((row) => row.slug === requestedSlug) || data.products[0];
  if (!product) return;

  let productName = prettySlug(product.slug);
  let images = orderedImages(product);
  let activeImage = 0;

  const root = document.createElement('div');
  root.className = 'showcase-root';
  const modal = document.createElement('div');
  modal.className = 'showcase-modal';
  modal.hidden = true;
  modal.innerHTML = '<button class="modal-close" type="button" aria-label="閉じる">×</button><button class="modal-nav modal-prev" type="button" aria-label="前の画像">←</button><img alt="拡大レンダリング"><button class="modal-nav modal-next" type="button" aria-label="次の画像">→</button>';

  const technicalRows = (rows, kind) => (rows || []).map((row) => {
    const href = safeHref(row.href);
    const detail = kind === 'gate'
      ? `${esc(row.status || '')}${row.detail ? ` · ${esc(row.detail)}` : ''}`
      : `${esc(row.status || '')}${row.sha256 ? ` · SHA-256 ${esc(row.sha256).slice(0, 16)}…` : ''}`;
    return `<div class="info-row"><strong>${esc(kind === 'gate' ? row.name : row.label)}</strong><span>${detail}${href ? ` · <a href="${href}">証拠を開く</a>` : ''}</span></div>`;
  }).join('');

  function galleryMarkup() {
    if (!images.length) {
      return `
        <div class="gallery-main">
          <div class="gallery-empty">
            <div><strong>レンダリング画像はまだ登録されていません</strong><span>Previews/ に実レンダリングが追加されると、この領域が商品ギャラリーになります。</span></div>
          </div>
        </div>
        <div class="gallery-caption"><span>render preview</span><span>0 images</span></div>`;
    }
    const active = images[activeImage] || images[0];
    return `
      <div class="gallery-main">
        <img src="${safeHref(active.href)}" alt="${esc(productName)} ${esc(active.name)} レンダリング">
        <button type="button" data-open-modal="${activeImage}" aria-label="${esc(active.name)} を拡大表示">拡大</button>
      </div>
      <div class="gallery-caption"><span>${esc(active.kind)} / ${esc(active.name)}</span><span>${activeImage + 1} / ${images.length}</span></div>
      <div class="thumb-strip" aria-label="レンダリング一覧">
        ${images.map((asset, index) => `<button class="thumb" type="button" data-thumb="${index}" aria-current="${index === activeImage}"><img src="${safeHref(asset.href)}" alt="${esc(asset.name)}"><span class="thumb-label">${esc(asset.name)}</span></button>`).join('')}
      </div>`;
  }

  function renderWallMarkup() {
    if (!images.length) return '<div class="gallery-empty"><div><strong>画像待ち</strong><span>別製品の画像で代用せず、この製品の実レンダリングだけを表示します。</span></div></div>';
    return images.map((asset, index) => `
      <article class="render-tile">
        <button type="button" data-open-modal="${index}" aria-label="${esc(asset.name)} を拡大表示"><img src="${safeHref(asset.href)}" alt="${esc(productName)} ${esc(asset.name)}"></button>
        <div class="render-tile-meta"><span>${esc(asset.kind)} / ${esc(asset.name)}</span><span>${esc(asset.status)}</span></div>
      </article>`).join('');
  }

  function otherProductsMarkup() {
    const others = data.products.filter((row) => row.slug !== product.slug).slice(0, 8);
    if (!others.length) return '<p>ほかの製品はありません。</p>';
    return others.map((row) => {
      const preview = orderedImages(row)[0];
      const media = preview
        ? `<img src="${safeHref(preview.href)}" alt="${esc(row.slug)} レンダリング">`
        : '<div class="other-card-placeholder">NO RENDER</div>';
      return `<a class="other-card" href="?product=${encodeURIComponent(row.slug)}">${media}<div class="other-card-body"><strong>${esc(prettySlug(row.slug))}</strong><small>${esc(stateLabel(row.state))}</small></div></a>`;
    }).join('');
  }

  function render() {
    const manifestHref = safeHref(product.manifest_href);
    const reviewHref = safeHref(product.human_review_url);
    const blockers = product.blockers || [];
    const passedImages = (product.assets || []).filter((asset) => asset.href && asset.status === 'PASS').length;

    root.innerHTML = `
      <header class="showcase-header">
        <a class="showcase-brand" href="${location.pathname}">image2outfit <small>RENDER SHOWCASE</small></a>
        <nav class="showcase-header-links" aria-label="サイトナビゲーション">
          <a href="#renders">レンダリング</a>
          <a href="https://github.com/KAFKA2306/image2outfit" target="_blank" rel="noreferrer">GitHub ↗</a>
        </nav>
      </header>
      <main class="showcase-main">
        <section class="product-stage" aria-labelledby="product-name">
          <div class="gallery-shell" id="gallery-shell">${galleryMarkup()}</div>
          <aside class="product-panel">
            <p class="product-kicker">3D GARMENT / RENDERED RESULT</p>
            <h1 id="product-name">${esc(productName)}</h1>
            <p class="product-slug">${esc(product.slug)}</p>
            <div class="status-row">
              <span class="status-pill" data-state="${esc(product.state)}">${esc(stateLabel(product.state))}</span>
              <span class="status-pill">${images.length} renders</span>
            </div>
            <p class="product-summary">実際のレンダリングを最初に確認し、必要なときだけ制作状態・品質証拠へ進める構成です。画像はこの製品に紐づく正準成果物だけを表示します。</p>
            <div class="primary-actions">
              ${images.length ? '<a class="primary-action" href="#renders">すべてのレンダリングを見る</a>' : ''}
              ${manifestHref ? `<a class="primary-action secondary-action" href="${manifestHref}">制作データを見る</a>` : ''}
              ${reviewHref ? `<a class="primary-action secondary-action" href="${reviewHref}" target="_blank" rel="noreferrer">レビューを開く ↗</a>` : ''}
            </div>
            <dl class="product-facts">
              <div class="product-fact"><dt>画像</dt><dd>${passedImages} / ${(product.assets || []).length}</dd></div>
              <div class="product-fact"><dt>状態</dt><dd>${esc(stateLabel(product.state))}</dd></div>
              <div class="product-fact"><dt>blocker</dt><dd>${Number(product.blocker_count || 0)}</dd></div>
              <div class="product-fact"><dt>更新</dt><dd>${esc(formatDate(product.updated_at))}</dd></div>
            </dl>
          </aside>
        </section>

        <section class="section-block" id="renders">
          <div class="section-head"><h2>レンダリング</h2><p>正面・斜め・背面・ポーズなど、登録済みの実画像を大きく並べます。クリックで原寸に近い状態へ拡大できます。</p></div>
          <div class="render-wall">${renderWallMarkup()}</div>
        </section>

        <section class="section-block">
          <div class="section-head"><h2>制作・品質情報</h2><p>画像を見たあとで必要になる検証情報です。販売・作品閲覧の主導線からは一段下げています。</p></div>
          <div class="info-grid">
            <details class="info-card"><summary>未解決blocker <span>${blockers.length}</span></summary><div class="info-body">${blockers.length ? `<ul>${blockers.map((row) => `<li><strong>${esc(row.severity)}</strong> ${esc(row.message)}</li>`).join('')}</ul>` : '<p>未解決blockerなし</p>'}</div></details>
            <details class="info-card"><summary>release gate <span>${(product.gates || []).length}</span></summary><div class="info-body">${technicalRows(product.gates, 'gate') || '<p>登録なし</p>'}</div></details>
            <details class="info-card"><summary>証拠 <span>${(product.evidence || []).length}</span></summary><div class="info-body">${technicalRows(product.evidence, 'evidence') || '<p>登録なし</p>'}</div></details>
            <details class="info-card"><summary>再開情報</summary><div class="info-body"><div class="info-row"><strong>resume point</strong><span>${esc(product.resume_point)}</span></div><div class="info-row"><strong>candidate hash</strong><span>${esc(product.candidate_hash)}</span></div></div></details>
          </div>
        </section>

        <section class="section-block">
          <div class="section-head"><h2>ほかの衣装</h2><p>製品を切り替えて、同じ画像中心のレイアウトで比較できます。</p></div>
          <div class="other-grid">${otherProductsMarkup()}</div>
        </section>
        <footer class="showcase-footer">image2outfit · canonical render evidence</footer>
      </main>`;

    document.title = `${productName} — image2outfit`;
    bindEvents();
  }

  function bindEvents() {
    root.querySelectorAll('[data-thumb]').forEach((button) => {
      button.addEventListener('click', () => {
        activeImage = Number(button.dataset.thumb) || 0;
        const gallery = root.querySelector('#gallery-shell');
        if (gallery) gallery.innerHTML = galleryMarkup();
        bindEvents();
      });
    });
    root.querySelectorAll('[data-open-modal]').forEach((button) => {
      button.addEventListener('click', () => openModal(Number(button.dataset.openModal) || 0));
    });
  }

  function openModal(index) {
    if (!images.length) return;
    activeImage = (index + images.length) % images.length;
    modal.querySelector('img').src = images[activeImage].href;
    modal.querySelector('img').alt = `${productName} ${images[activeImage].name} 拡大レンダリング`;
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
  }
  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = '';
  }
  function moveModal(delta) { openModal(activeImage + delta); }

  modal.querySelector('.modal-close').addEventListener('click', closeModal);
  modal.querySelector('.modal-prev').addEventListener('click', () => moveModal(-1));
  modal.querySelector('.modal-next').addEventListener('click', () => moveModal(1));
  modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(); });
  document.addEventListener('keydown', (event) => {
    if (modal.hidden) return;
    if (event.key === 'Escape') closeModal();
    if (event.key === 'ArrowLeft') moveModal(-1);
    if (event.key === 'ArrowRight') moveModal(1);
  });

  document.body.append(root, modal);
  document.body.classList.add('showcase-ready');
  render();

  if (product.manifest_href) {
    fetch(product.manifest_href)
      .then((response) => response.ok ? response.json() : null)
      .then((manifest) => {
        const name = manifest?.productName || manifest?.name;
        if (!name || name === productName) return;
        productName = name;
        render();
      })
      .catch(() => {});
  }
})();

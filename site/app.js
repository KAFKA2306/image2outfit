const REPO_URL = "https://github.com/KAFKA2306/image2outfit";
const RAW_ROOT = "https://raw.githubusercontent.com/KAFKA2306/image2outfit/main/";
const CATALOG_URL = `${RAW_ROOT}Assets/GenWorks/OutfitCatalog.json`;

const grid = document.querySelector("#catalog-grid");
const coverageGrid = document.querySelector("#coverage-grid");
const statusNode = document.querySelector("#catalog-status");
const productCountNode = document.querySelector("#product-count");

const hero = {
  primaryImage: document.querySelector("#hero-primary-image"),
  primaryName: document.querySelector("#hero-primary-name"),
  primaryStatus: document.querySelector("#hero-primary-status"),
  secondaryImage: document.querySelector("#hero-secondary-image"),
  secondaryName: document.querySelector("#hero-secondary-name"),
  secondaryStatus: document.querySelector("#hero-secondary-status"),
};

function githubTreeUrl(path) {
  return `${REPO_URL}/tree/main/${path}`;
}

function rawAssetUrl(path) {
  return `${RAW_ROOT}${path}`;
}

function statusClass(status = "") {
  return `status-${status.toLowerCase().replace(/[^a-z0-9-]/g, "-")}`;
}

function readableClassification(value = "") {
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function frontPreviewUrl(product) {
  return rawAssetUrl(`${product.productRoot}/Previews/front.png`);
}

function markMissingImage(image) {
  image.classList.add("is-missing");
  image.removeAttribute("src");
}

function bindImage(image, product, eager = false) {
  image.loading = eager ? "eager" : "lazy";
  image.alt = `${product.productName} の正準frontプレビュー`;
  image.src = frontPreviewUrl(product);
  image.addEventListener("error", () => markMissingImage(image), { once: true });
}

function setHeroProduct(product, image, nameNode, statusNodeForHero) {
  if (!product) return;
  bindImage(image, product, true);
  nameNode.textContent = product.productName;
  statusNodeForHero.textContent = product.status;
}

function renderHero(products) {
  setHeroProduct(products[0], hero.primaryImage, hero.primaryName, hero.primaryStatus);
  setHeroProduct(products[1] || products[0], hero.secondaryImage, hero.secondaryName, hero.secondaryStatus);
}

function createCoverageFigure(product) {
  const figure = document.createElement("figure");
  const image = document.createElement("img");
  bindImage(image, product);

  const caption = document.createElement("figcaption");
  caption.textContent = `${product.productName} · ${product.status}`;

  figure.append(image, caption);
  return figure;
}

function renderCoverage(products) {
  const examples = products.slice(0, 4);
  coverageGrid.replaceChildren(...examples.map(createCoverageFigure));
}

function createProductCard(product) {
  const article = document.createElement("article");
  article.className = "product-card";
  article.dataset.productId = product.productId;

  const media = document.createElement("div");
  media.className = "product-media";

  const fallback = document.createElement("div");
  fallback.className = "product-fallback";
  fallback.textContent = "preview unavailable";

  const image = document.createElement("img");
  bindImage(image, product);

  const badge = document.createElement("span");
  badge.className = `product-status ${statusClass(product.status)}`;
  badge.textContent = product.status;

  media.append(fallback, image, badge);

  const body = document.createElement("div");
  body.className = "product-body";

  const id = document.createElement("p");
  id.className = "product-id";
  id.textContent = product.productId;

  const title = document.createElement("h3");
  title.textContent = product.productName;

  const classification = document.createElement("p");
  classification.className = "product-classification";
  classification.textContent = readableClassification(product.classification);

  const link = document.createElement("a");
  link.className = "product-link";
  link.href = githubTreeUrl(product.productRoot);
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "製品ワークスペースを見る ↗";
  link.setAttribute("aria-label", `${product.productName} の製品ワークスペースをGitHubで開く`);

  body.append(id, title, classification, link);
  article.append(media, body);
  return article;
}

function renderCatalog(catalog) {
  const products = Array.isArray(catalog.activeProducts) ? catalog.activeProducts : [];
  grid.replaceChildren(...products.map(createProductCard));
  renderHero(products);
  renderCoverage(products);

  const count = Number.isFinite(catalog.configuredProductCount)
    ? catalog.configuredProductCount
    : products.length;

  productCountNode.textContent = new Intl.NumberFormat("ja-JP").format(count);
  statusNode.textContent = `${products.length}件を main の正準カタログから表示しています。Hero・Coverage・Catalogは同じデータを参照しています。`;
}

function renderCatalogError() {
  productCountNode.textContent = "—";
  statusNode.textContent = "正準カタログを取得できませんでした。";

  const message = document.createElement("div");
  message.className = "catalog-error";
  message.textContent = "表示用JSONの取得に失敗しました。製品状態はGitHubの OutfitCatalog.json で確認できます。";
  grid.replaceChildren(message);
  coverageGrid.replaceChildren();
}

async function loadCatalog() {
  try {
    const response = await fetch(CATALOG_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Catalog request failed: ${response.status}`);
    }

    const catalog = await response.json();
    renderCatalog(catalog);
  } catch (error) {
    console.error(error);
    renderCatalogError();
  }
}

loadCatalog();

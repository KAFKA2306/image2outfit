const REPO_URL = "https://github.com/KAFKA2306/image2outfit";
const RAW_ROOT = "https://raw.githubusercontent.com/KAFKA2306/image2outfit/main/";
const CATALOG_URL = `${RAW_ROOT}Assets/GenWorks/OutfitCatalog.json`;
const requestedProductId = new URLSearchParams(window.location.search).get("product");

const grid = document.querySelector("#catalog-grid");
const coverageGrid = document.querySelector("#coverage-grid");
const exampleGallery = document.querySelector("#example-gallery");
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

const EXAMPLE_VIEWS = [
  { file: "front.png", label: "front" },
  { file: "three-quarter.png", label: "three-quarter" },
  { file: "back.png", label: "back" },
];

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

function previewUrl(product, filename = "front.png") {
  return rawAssetUrl(`${product.productRoot}/Previews/${filename}`);
}

function frontPreviewUrl(product) {
  return previewUrl(product, "front.png");
}

function markMissingImage(image) {
  image.classList.add("is-missing");
  image.removeAttribute("src");
}

function bindImage(image, product, eager = false, filename = "front.png", viewLabel = "front") {
  image.loading = eager ? "eager" : "lazy";
  image.alt = `${product.productName} の正準${viewLabel}プレビュー`;
  image.src = previewUrl(product, filename);
  image.addEventListener("error", () => markMissingImage(image), { once: true });
}

function isRequestedProduct(product) {
  return Boolean(requestedProductId) && product.productId === requestedProductId;
}

function prioritizeRequestedProduct(products) {
  if (!requestedProductId) return products;
  const selectedIndex = products.findIndex(isRequestedProduct);
  if (selectedIndex < 0) return products;
  return [products[selectedIndex], ...products.filter((_, index) => index !== selectedIndex)];
}

function markSelected(node, product) {
  if (!isRequestedProduct(product)) return;
  node.classList.add("is-selected");
  node.setAttribute("aria-current", "true");
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

function createExampleView(product, view) {
  const frame = document.createElement("div");
  frame.className = "example-view";

  const fallback = document.createElement("div");
  fallback.className = "example-view-fallback";
  fallback.textContent = `${view.label} preview unavailable`;

  const image = document.createElement("img");
  bindImage(image, product, false, view.file, view.label);

  const label = document.createElement("span");
  label.className = "example-view-label";
  label.textContent = view.label;

  frame.append(fallback, image, label);
  return frame;
}

function createExampleCard(product) {
  const article = document.createElement("article");
  article.className = "example-card";
  markSelected(article, product);

  const header = document.createElement("div");
  header.className = "example-card-header";

  const titleWrap = document.createElement("div");
  titleWrap.className = "example-card-title";

  const id = document.createElement("p");
  id.textContent = product.productId;

  const title = document.createElement("h3");
  title.textContent = product.productName;

  titleWrap.append(id, title);

  const badge = document.createElement("span");
  badge.className = `example-card-status ${statusClass(product.status)}`;
  badge.textContent = product.status;

  header.append(titleWrap, badge);

  const views = document.createElement("div");
  views.className = "example-views";
  views.replaceChildren(...EXAMPLE_VIEWS.map((view) => createExampleView(product, view)));

  const footer = document.createElement("div");
  footer.className = "example-card-footer";

  const note = document.createElement("p");
  note.textContent = `${readableClassification(product.classification)} · canonical render evidence`;

  const link = document.createElement("a");
  link.className = "example-card-link";
  link.href = githubTreeUrl(product.productRoot);
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "この実例の証拠を見る ↗";
  link.setAttribute("aria-label", `${product.productName} の製品ワークスペースをGitHubで開く`);

  footer.append(note, link);
  article.append(header, views, footer);
  return article;
}

function examplePriority(product) {
  if (product.status === "COMPLETE") return 0;
  if (product.status === "WORKING") return 1;
  if (product.status === "REJECTED") return 2;
  return 3;
}

function renderExamples(products) {
  if (!exampleGallery) return;

  const examples = [...products]
    .sort((a, b) => {
      if (isRequestedProduct(a)) return -1;
      if (isRequestedProduct(b)) return 1;
      return examplePriority(a) - examplePriority(b);
    })
    .slice(0, 4);

  if (!examples.length) {
    const empty = document.createElement("div");
    empty.className = "example-gallery-empty";
    empty.textContent = "表示できる正準製品がありません。";
    exampleGallery.replaceChildren(empty);
    return;
  }

  exampleGallery.replaceChildren(...examples.map(createExampleCard));
}

function createProductCard(product) {
  const article = document.createElement("article");
  article.className = "product-card";
  article.dataset.productId = product.productId;
  markSelected(article, product);

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
  const sourceProducts = Array.isArray(catalog.activeProducts) ? catalog.activeProducts : [];
  const products = prioritizeRequestedProduct(sourceProducts);
  const selected = products.find(isRequestedProduct);

  grid.replaceChildren(...products.map(createProductCard));
  renderHero(products);
  renderExamples(products);
  renderCoverage(products);

  const count = Number.isFinite(catalog.configuredProductCount)
    ? catalog.configuredProductCount
    : products.length;

  productCountNode.textContent = new Intl.NumberFormat("ja-JP").format(count);
  if (selected) {
    document.title = `${selected.productName} — image2outfit`;
    statusNode.textContent = `${selected.productName} を選択中。${products.length}件を main の正準カタログから表示しています。`;
  } else {
    statusNode.textContent = `${products.length}件を main の正準カタログから表示しています。Examples・Hero・Coverage・Catalogは同じデータを参照しています。`;
  }
}

function renderCatalogError() {
  productCountNode.textContent = "—";
  statusNode.textContent = "正準カタログを取得できませんでした。";

  const message = document.createElement("div");
  message.className = "catalog-error";
  message.textContent = "表示用JSONの取得に失敗しました。製品状態はGitHubの OutfitCatalog.json で確認できます。";
  grid.replaceChildren(message);
  coverageGrid.replaceChildren();
  if (exampleGallery) {
    const exampleError = document.createElement("div");
    exampleError.className = "example-gallery-empty";
    exampleError.textContent = "実例を取得できませんでした。正準カタログを確認してください。";
    exampleGallery.replaceChildren(exampleError);
  }
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

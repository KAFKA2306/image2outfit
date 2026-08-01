# GenWorks

このディレクトリは、image2outfitで制作する衣装アセットの正規ルートです。

- `Products/` — 製品ごとの完結したUnityアセット
- `Shared/` — 複数製品で共有するEditor拡張、検証、共通マテリアル
- `Legacy/` — 旧配置から移行した監査対象。新規制作では使用しない

Unityでは `GenWorks > Product Catalog` を開くと、製品状態、衣装Prefab、統合確認Prefab、プレビュー、導入文書を一覧で確認できます。

新規製品は `Assets/GenWorks/Products/<product-slug>/ProductManifest.json` を持ち、販売対象ファイルを製品フォルダ内だけで完結させます。購入アバター本体、ライセンス証拠、ローカルジョブ、生成キャッシュは `Assets/_Local` または `Assets/_Vendor` に保持し、ここへ複製しません。

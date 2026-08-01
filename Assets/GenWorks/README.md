# GenWorks

このディレクトリは、image2outfitで制作・検証するUnityアセットの正規ルートです。

- `Products/` — 製品ごとの完結したUnityアセット
- `Shared/` — 複数製品で共有するEditor拡張、検証、共通マテリアル
- `Legacy/Snapshots/` — 旧配置から移行した監査対象。新規制作や自動リリースには使用しない

履歴スナップショットは `Assets/GenWorks/Legacy/Snapshots/` にのみ配置します。旧リポジトリ直下の `Published/` と旧中間配置 `Assets/GenWorks/Legacy/Published/` は禁止です。Unity ProjectウィンドウからFBX、Prefab、テクスチャ、プレビュー、監査証拠を直接確認できますが、`Products/` の製品カタログには登録せず、販売可能判定にも自動昇格させません。

Unityでは `GenWorks > Product Catalog` を開くと、現行製品の状態、衣装Prefab、統合確認Prefab、プレビュー、導入文書を一覧で確認できます。

新規製品は `Assets/GenWorks/Products/<product-slug>/ProductManifest.json` を持ち、販売対象ファイルを製品フォルダ内だけで完結させます。購入アバター本体、ライセンス証拠、ローカルジョブ、生成キャッシュは `Assets/_Local` または `Assets/_Vendor` に保持し、ここへ複製しません。

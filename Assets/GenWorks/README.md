# GenWorks

`Assets/GenWorks` は、image2outfitで制作・検証するUnityアセットの**正規かつ再開可能な作業ルート**です。完成品だけを置く場所ではありません。作業途中でも、別の開発者・エージェントがUnityを開いて同じ地点から継続できる状態をGitで保持します。

## ディレクトリ

- `Products/<product-id>/` — 製品単位の作業・技術検証・納品候補を完結させる
- `Shared/` — 複数製品で共有するEditor拡張、検証コード、共通マテリアル、汎用Unity処理
- `Legacy/Snapshots/` — 旧配置から移行した参照専用スナップショット。新規制作や自動リリースには使用しない

旧リポジトリ直下の `Published/` と旧中間配置 `Assets/GenWorks/Legacy/Published/` は禁止です。購入アバター本体、秘密情報、ローカルジョブ、生成キャッシュは `Assets/_Local` または `Assets/_Vendor` に保持し、GenWorksへ複製しません。

## 製品ワークスペース契約

各 `Products/<product-id>/` は、該当する範囲で次の状態を保持します。

- `ProductManifest.json` — 現在状態、対象アバター、再開地点、技術ゲート、未解決事項
- `Source/Blender/` — 再生成可能な `.blend`
- `Source/Generators/` — 製品固有ロジック。汎用処理は `tools/` または `Shared/` に置く
- `Models/` — FBXとUnity `.meta`
- `Textures/` / `Materials/` — Unityで復元可能なテクスチャ・マテリアル設定
- `Prefabs/Outfit/` — 衣装単体Prefab
- `Prefabs/Integrated/<target>/` — 対象アバターへ組み込むPrefab
- `Demo/` / `Tests/` / `Editor/` — Unityでの自動検証、保存・再読込、導入確認
- `Previews/` — 5方向、ポーズ、必要に応じUnity/runtimeの実レンダリング証拠
- `Documentation/` または `README.md` — 導入方法、制約、未解決事項

**引き継ぎ可能とみなす最低条件**は、BlenderやFBXだけではありません。衣装Prefabと統合Prefabを作成し、必要なUnity設定をシリアライズした状態まで進めます。対象に応じて、Modular Avatar/NDMF、Armature Link、Merge Armature、メニュー・パラメータ、Animator、constraints、PhysBones、colliders、material overridesなどをPrefab内へ保存します。

## 状態

- `WORKING` — Git追跡済みで再開可能。ただし自動技術ゲートに未完了がある
- `TECHNICAL_READY` — Blender、FBX、Unity import、Prefab作成、保存・再読込、必要なUnity設定、自動統合検証が完了
- `HUMAN_REVIEW_PENDING` — 技術的には完了し、最終の見た目・ポーズ・VRChat runtime確認待ち
- `RELEASED` — 同一候補ハッシュに対する人間レビューとrelease gateが完了
- `REJECTED` — 問題と証拠を残した再開可能な却下状態。黙って削除・ゼロから再作成しない

`MODELED` のような曖昧な状態は新規に使用しません。Unity設定が未完了なら `WORKING`、自動Unity検証まで完了していれば `TECHNICAL_READY` または `HUMAN_REVIEW_PENDING` とします。

## 運用原則

Actions artifactはログ・一時バンドル・監査証拠の輸送に使用しますが、唯一の成果物保管場所にはしません。技術的に有効な途中成果は、通常のbranch/PRを通じて `Assets/GenWorks/<product-id>/` に反映します。

作業開始時は、既存の `ProductManifest.json`、Prefab、統合Prefab、最新レンダリング、監査結果を先に確認します。既存チェックポイントがある場合、別branchでゼロから同じ生成を繰り返してはいけません。

Unityでは `GenWorks > Product Catalog` を開き、現行製品の状態、衣装Prefab、統合確認Prefab、プレビュー、導入文書を確認します。最終の人間によるUnity/VRChat確認前であっても、Unity設定済みPrefabまでを正規ワークスペースへ保持します。ただし、人間レビュー未完了の状態を販売可能・完成済みとは表示しません。

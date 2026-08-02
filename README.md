# image2outfit — VRChat衣装の再現可能な制作・納品パイプライン

**リポジトリ:** https://github.com/KAFKA2306/image2outfit

image2outfitは、参考画像からVRChatアバター向け衣装を制作し、Blender、Unity、VRChatでの検証証拠をそろえてから納品候補へ進めるためのパイプラインです。

メッシュが生成できた、FBXが読み込めた、Prefabが存在するというだけでは完成扱いにしません。見た目、身体へのフィット、ポーズ時の貫通、VRChat内動作、人間による確認までを別々のゲートとして記録します。

## 現在の状態

- 再現可能なBlender → FBX → Unity Prefab候補生成を実装
- Blender Python環境とVPM依存関係を固定・監査
- 正面、背面、左右、斜めの5方向プレビューを必須化
- 候補ファイルとレビュー証拠をハッシュで固定
- 技術検証だけでは自動的に販売・リリース判定へ進まない
- 制作物の正規ルートを`Assets/GenWorks/`へ統一
- 製品固有設定を`config/products/<product-id>/`へ分離
- GitHub Actionsが`main`へ状態JSONや生成物を直接pushする経路を禁止
- 履歴スナップショットを`Assets/GenWorks/Legacy/Snapshots/`へ統一
- 旧`Published/`、一時トリガーファイル、実行状態スナップショットの再作成をCIで禁止

`config/release-policy.json`はアバターごとの主要対象を固定せず、禁止対象と共通リリース条件だけを定義します。制作対象は各job v2の`adapterId`で明示します。

## 設定の境界

共通契約と製品固有情報を混在させません。

```text
config/
  job.schema.v2.json
  release-policy.json
  genworks-layout.json
  toolchain-lock.json
  blender-python-requirements.txt
  products/
    <product-id>/
      job.json
      license.json

examples/
  review-approval.json
```

- `config/`直下は全製品に適用される契約だけを置く
- `config/products/<product-id>/job.json`は生成・検証・納品対象を定義する
- `license.json`は同じ製品設定ディレクトリに置く
- 購入アバター、非公開ソース、人間レビュー証拠は`Assets/_Local/`または`Assets/_Vendor/`に置き、Git管理しない
- 承認入力は`examples/review-approval.json`を複製して作成する

## Assets/GenWorks

Unityで開発者と購入者が迷わないよう、販売対象、統合確認用、制作ソース、プレビュー、検証コードを製品単位で分離します。

```text
Assets/GenWorks/
  Products/
    <product-id>/
      ProductManifest.json
      README.md
      Source/Blender/
      Models/
      Textures/
      Materials/
      Prefabs/
        Outfit/
        Integrated/<target-avatar>/
      Previews/
      Demo/
      Editor/
      Tests/
      Documentation/
  Shared/
    Editor/
    Materials/
    Shaders/
    Templates/
    Validation/
  Legacy/
    Snapshots/
      LegacyManifest.json
      <historical snapshots>/
```

新規製品は`ProductManifest.json`を持ち、製品内の主要アセットをUnityカタログへ公開します。購入・非公開アバター本体、ライセンス証拠、ローカルjob、キャッシュは製品フォルダへ混入させません。

`Assets/GenWorks/Legacy/Snapshots/`は過去のFBX、Prefab、テクスチャ、プレビュー、監査証拠を確認するための唯一の履歴領域です。現行製品カタログには登録せず、販売可能判定へ自動昇格させません。

## 基本操作

リポジトリ全体の残骸・境界違反を監査します。

```powershell
task audit:repo
```

GenWorks構造を監査します。

```powershell
task audit:genworks
```

追跡済み製品jobから候補を作ります。

```powershell
task candidate JOB=config/products/<product-id>/job.json
```

非公開アバターやローカル専用jobを使う場合も同じコマンドです。

```powershell
task candidate JOB=Assets/_Local/Jobs/<job-id>/job.json
```

技術検証が成功しても判定は`REVIEW_REQUIRED`です。`Release/`には書き込みません。

レビュー済み候補をリリースします。

```powershell
task release JOB=config/products/<product-id>/job.json
```

再ビルドは行わず、レビュー済み候補、入力ファイル、証拠ファイルのハッシュが変わっていないことを確認します。判定が`GO`の場合だけ`Release/<job-id>/`とZIPを生成します。

GitHub-hosted Blenderだけで生成確認する場合は、Actionsの`Build product with hosted Blender`を手動実行し、`config/products/<product-id>/job.json`を渡します。生成物はartifactへ保存され、workflowは`main`を変更しません。

## メンテナンス

既存ローカルjobの移行計画を確認します。

```powershell
task maintenance:migrate:genworks
```

確認後に移行します。

```powershell
task maintenance:migrate:genworks:apply
```

任意の履歴スナップショットを監査します。

```powershell
task audit:snapshot SNAPSHOT=<snapshot-path> SOURCE=<local-source-path>
```

任意の履歴スナップショットを再パッケージします。

```powershell
task package:snapshot SNAPSHOT=<snapshot-path>
```

## リリース条件

衣装を`GO / RELEASED`へ進めるには、少なくとも次をすべて満たす必要があります。

1. 対象アバター本体と利用許諾の証拠が存在する
2. Blenderで編集可能な`.blend`と構造エラーのないFBXを生成できる
3. 固定されたUnityバージョンでFBXを読み込み、対象アバターとの統合を検証できる
4. 1024×1024以上の5方向プレビューがある
5. 人間がシルエット、フィット、素材表現、見栄えを承認する
6. 通常、腕上げ、腕組み、しゃがみ、座り、伏せで重大な貫通がない
7. VRChat SDK Build & TestとVRChatクライアント内確認を通過する
8. すべてのレビューが同一候補のmanifest hashへ結び付いている

```text
SPECIFIED
  → MODELED
  → TECHNICAL_PASS
  → REVIEW_REQUIRED
  → VISUAL_PASS
  → POSE_PASS
  → RUNTIME_PASS
  → GO / RELEASED
```

失敗または証拠不足がある場合は`NO-GO`です。`TECHNICAL_PASS`から`GO`へ自動昇格する経路はありません。

## 固定ツールチェーン

`config/toolchain-lock.json`でBlender、Blender Python、Pythonパッケージ、Unity、VRChat SDK、Modular Avatar、NDMF、Avatar Optimizerを固定します。

```bash
python tools/audit_toolchain.py
```

詳細は[docs/TOOLCHAIN.md](docs/TOOLCHAIN.md)を参照してください。

## 権利と秘密情報の分離

正規の非公開領域は次です。

```text
Assets/_Local/
Assets/_Vendor/
Assets/_Reference/
```

納品対象はjob内の`deliveryAssets`へ明示的に列挙します。`privateSourceRoots`配下のファイルを納品物へ混入させると検証に失敗します。

## 証拠と契約

- `Artifacts/<job-id>/audit.json` — 現在の判定と各ゲート結果
- `Candidates/<job-id>/candidate-manifest.json` — 候補の入力・出力・ハッシュ
- `Release/<job-id>/release-manifest.json` — GO後の変更不能な記録
- `Assets/GenWorks/Products/<product-id>/ProductManifest.json` — Unity製品カタログ
- `Assets/GenWorks/Legacy/Snapshots/LegacyManifest.json` — 履歴スナップショット境界
- `config/products/<product-id>/job.json` — 製品固有の生成・検証・納品定義
- `config/job.schema.v2.json` — job定義と必須フィールドの唯一の情報源
- `config/genworks-layout.json` — GenWorks配置契約
- `config/release-policy.json` — 免除できないリリース条件
- `tools/release_gate.py` — 候補hashとリリース昇格の実装
- `tools/audit_repository_hygiene.py` — 残骸と境界違反の再発防止
- `ontology/project.yaml` — 制作・観測・判断の証拠モデル

詳細は[docs/GENWORKS_LAYOUT.md](docs/GENWORKS_LAYOUT.md)を参照してください。

**README最終監査:** 2026-08-02

# image2outfit — VRChat衣装の再現可能な制作・納品パイプライン

**リポジトリ:** https://github.com/KAFKA2306/image2outfit

image2outfitは、参考画像からVRChatアバター向け衣装を制作し、Blender、Unity、VRChatでの検証証拠をそろえてから納品候補へ進めるためのパイプラインです。

メッシュが生成できた、FBXが読み込めた、Prefabが存在するというだけでは完成扱いにしません。見た目、身体へのフィット、ポーズ時の貫通、VRChat内動作、人間による確認までを別々のゲートとして記録します。

## 現在の状態

- 再現可能なBlender → FBX → Unity Prefab候補生成を実装
- Blender Python環境とVPM依存関係を固定・監査
- SiroinoSotaiのCC0アセットを用いた衣装候補生成を追加
- 正面、背面、左右、斜めの5方向プレビューを必須化
- 候補ファイルとレビュー証拠をハッシュで固定
- 技術検証だけでは自動的に販売・リリース判定へ進まない
- 制作物の正規ルートを`Assets/GenWorks/`へ統一
- Unity内の`GenWorks > Product Catalog`から製品、Prefab、統合確認Prefab、プレビュー、文書へ直接移動可能
- 既存ローカルjobの成果物と`.meta`をGenWorksへ移す移行ツールを追加

`config/release-policy.json`上の主要アダプターは`pochi-v1.1.0`です。`haolan-v1.6`はリリース禁止対象であり、現時点では過去候補の研究・監査用途に限定します。

## Assets/GenWorks

Unityで開発者と購入者が迷わないよう、販売対象、統合確認用、制作ソース、プレビュー、検証コードを製品単位で分離します。

```text
Assets/GenWorks/
  Products/
    <product-slug>/
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
```

新規製品は`ProductManifest.json`を持ち、製品内の主要アセットをUnityカタログへ公開します。購入・非公開アバター本体、ライセンス証拠、ローカルjob、キャッシュは製品フォルダへ混入させません。

既存jobの移行計画を確認します。

```powershell
task migrate:genworks
```

確認後に移行します。アセットとUnityの`.meta`を一緒に移動し、jobパスと製品manifestを更新します。

```powershell
task migrate:genworks:apply
```

構造監査:

```powershell
task audit:genworks
```

詳細は[docs/GENWORKS_LAYOUT.md](docs/GENWORKS_LAYOUT.md)を参照してください。

## リリース条件

衣装を`GO / RELEASED`へ進めるには、少なくとも次をすべて満たす必要があります。

1. 対象アバター本体と利用許諾の証拠がローカルに存在する
2. Blenderで編集可能な`.blend`と構造エラーのないFBXを生成できる
3. Unity 2022.3.22f1でFBXを読み込み、対象アバターとの統合を検証できる
4. 1024×1024以上の5方向プレビューがある
5. 人間がシルエット、フィット、素材表現、見栄えを承認する
6. 通常、腕上げ、腕組み、しゃがみ、座り、伏せで重大な貫通がない
7. VRChat SDK Build & TestとVRChatクライアント内確認を通過する
8. すべてのレビューが同一候補のmanifest hashへ結び付いている

## 状態遷移

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

`config/toolchain-lock.json`で次を固定します。

- Blender 4.4.3
- Blender Python 3.11.11
- Pillow 12.3.0
- Unity 2022.3.22f1
- VRChat SDK 3.10.4
- Modular Avatar 1.17.1
- NDMF 1.14.1
- Avatar Optimizer 1.9.16

検証:

```bash
python tools/audit_toolchain.py
```

詳細は[docs/TOOLCHAIN.md](docs/TOOLCHAIN.md)を参照してください。

## 1. 納品候補を作る

```powershell
task candidate JOB=Assets/_Local/Jobs/<job-id>/job.json
```

この処理はBlender・Unityの静的検証、5方向プレビュー、`deliveryAssets`の明示的な収集、候補manifestの生成を行います。

技術検証が成功しても判定は`REVIEW_REQUIRED`です。`Release/`には書き込みません。

## 2. レビュー済み候補をリリースする

```powershell
task release JOB=Assets/_Local/Jobs/<job-id>/job.json
```

再ビルドは行わず、レビュー済み候補、入力ファイル、証拠ファイルのハッシュが変わっていないことを確認します。判定が`GO`の場合だけ`Release/<job-id>/`とZIPを生成します。

## 権利と秘密情報の分離

購入・非公開アバターやライセンス対象データは、Git管理外の次のようなローカル領域に保持します。

```text
Assets/_Local/
Assets/_Vendor/
Assets/PochibyKT/
Assets/HAOLAN_Quest/
```

納品対象はjob内の`deliveryAssets`へ明示的に列挙します。非公開ルート配下のファイルを納品物へ混入させると検証に失敗します。

## 証拠ファイル

- `Artifacts/<job-id>/audit.json` — 現在の判定と各ゲート結果
- `Candidates/<job-id>/candidate-manifest.json` — 候補の入力・出力・ハッシュ
- `Release/<job-id>/release-manifest.json` — GO後の変更不能な記録
- `Assets/GenWorks/Products/<product-slug>/ProductManifest.json` — Unity製品カタログ
- `docs/GENWORKS_LAYOUT.md` — Unityアセット配置と移行仕様
- `docs/REVIEW_EVIDENCE.md` — 人間レビュー証拠の仕様
- `config/job.schema.v2.json` — job定義
- `config/genworks-layout.json` — GenWorks配置契約
- `config/release-policy.json` — 免除できないリリース条件
- `ontology/project.yaml` — 制作・観測・判断の証拠モデル

`Published/`配下の既存ファイルは過去のスナップショットであり、新しい顧客向けリリースではありません。既存のローカルjob成果物は`task migrate:genworks:apply`でUnity可視の製品構造へ移行します。

**README最終監査:** 2026-08-02

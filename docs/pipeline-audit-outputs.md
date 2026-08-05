# 13工程の監査可能な出力

衣装パイプラインは、工程の終了コードやメモリ上の戻り値だけを成功根拠にしません。`PLAN`と`EXECUTE`の両方で、実行単位の監査記録を`.image2outfit/audit/<productId>/<runId>/`へ保存します。

## 保存構造

```text
.image2outfit/audit/<productId>/
├── latest.json
└── <runId>/
    ├── manifest.json
    ├── pipeline-state.json
    └── stages/
        ├── 01-ingest-reference.json
        ├── 02-normalize-view.json
        ├── ...
        └── 13-finalize-candidate.json
```

各工程記録は、工程番号、工程名、要求モード、実際の結果、開始・終了時刻、ツール契約、入力ダイジェスト、出力ダイジェスト、前工程記録のダイジェスト、証拠ファイルとSHA-256、工程の完全な出力を保持します。前工程の`recordDigest`を次工程の`previousRecordDigest`へ入れるため、途中の工程記録を変更すると以後の連鎖検証が失敗します。

失敗した工程も`FAILED`記録とエラー型・エラー本文を保存します。したがって、失敗工程だけ監査証跡が欠落することはありません。

## 工程別に管理する出力

| 番号 | 工程 | 管理対象 |
|---:|---|---|
| 1 | `ingest-reference` | 参照manifest、原本SHA-256、来歴、対象アバターとの結合 |
| 2 | `normalize-view` | 正規化画像、カメラ姿勢、身体ランドマーク、正規化指標 |
| 3 | `decompose-garment` | 衣装部品グラフ、場所属性、素材領域、曖昧性ログ |
| 4 | `draft-patterns` | 型紙仕様、名前付き型紙辺、縫い代、ノッチ・ダーツ、画像・二次元・三次元対応 |
| 5 | `infer-stitches` | 縫合グラフ、型紙辺の対応、縫合方向、位相検証 |
| 6 | `initialize-3d` | 三次元初期メッシュ、各パネル変換、初期クリアランス監査 |
| 7 | `build-blender` | 編集可能Blend、構築報告、形状指標 |
| 8 | `simulate-cloth` | クロスキャッシュ、シミュレーション設定、衝突報告、評価済みメッシュ |
| 9 | `skin-and-export` | スキニング済みBlend、FBX、ウェイト監査、Prefab宣言 |
| 10 | `render-evidence` | 五面画像、必須ポーズ画像、レンダリングmanifest |
| 11 | `audit-geometry` | 形状監査、貫通監査、証拠hash監査、ゲート集計 |
| 12 | `visual-review` | 直接画像監査、確認画像hash、阻害事項 |
| 13 | `finalize-candidate` | 候補状態、完成ゲート記録、リリース判断 |

正準の名称は`config/pipeline-profiles/garment-reconstruction-v1.json`の各`managedOutputs`です。

## 状態境界

- 13工程の計画を記録した状態は`PLANNED`です。
- 13工程の実行結果と証拠を検証した状態は`EXECUTED`です。
- `EXECUTED`は製品の`COMPLETE`を意味しません。
- 製品状態`WORKING`、`COMPLETE`、`REJECTED`は既存の完成ゲートだけが決定します。

## 検証

`image2outfit.audit.verify_audit_bundle(run_root)`は次を再検証します。

1. 各工程ファイルのSHA-256
2. 各工程内部の`recordDigest`
3. `previousRecordDigest`による工程連鎖
4. `pipeline-state.json`のSHA-256
5. manifestの`chainHeadDigest`

CLIでは監査bundleの書込み後に同じ検証を実行し、検証できないbundleを正常終了として扱いません。監査先を変更する場合は`tools/run_garment_pipeline.py --audit-root <path>`を使用します。

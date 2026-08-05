# GarmentSpec v1 と型付き成果物DAG

## 目的

`GarmentSpec` は、13工程をまたいで衣服の同一性、仮説、単位、座標系、来歴、証拠hashを保持する正準ルート契約です。既存の `GarmentSpecification` が持つ型紙・縫合の詳細表現を置き換えず、各ドメイン成果物を参照する上位コンテナとして機能します。

## ルート構造

必須セクションは次の7領域です。

- `avatar`: 身体寸法、部位ランドマーク、ポーズ
- `construction`: 型紙、縫合、地の目、副資材
- `fit`: 部位別ゆとり、ひずみ、圧力、接触
- `materials`: 異方性布物性、厚さ、摩擦
- `styling`: アンカー、折り、開閉、レイヤー、非対称拘束
- `quality`: 原因別品質判定、証拠、戻り先
- `provenance`: 元参照、生成主体、証拠

各セクションは、独立したschema version、リポジトリ内の成果物パス、内容SHA-256、仮説ID、confidence、証拠を持ちます。単位系はミリメートル、座標系は右手系Z-upです。

## 未知情報の扱い

単一画像から判定できない背面、素材、縫合、留め具などを推定済みとして扱いません。移行fixtureでは、既存ファイルを `legacy-source-index` として索引化し、未整備セクションのconfidenceを0にしています。各詳細セクションは #140〜#145 で段階的に完成させます。

## 型付き成果物DAG

`PipelineArtifactDAG` は正規13工程を維持し、工程ごとに次を定義します。

- 消費する成果物の型
- 生成する成果物の型
- 変更時に無効化する `GarmentSpec` セクション

成果物は `garment_id`、`hypothesis_id`、`candidate_id`、avatar hashを保持します。別製品、別仮説、別候補、別avatarの成果物混入を拒否します。キャッシュを利用する場合は、宣言hashではなく実ファイルからSHA-256を再計算します。

## 再実行範囲

セクション変更から、必要な最初の工程と全下流工程を機械的に決定します。例として、素材変更は `build-blender` から、来歴変更は `ingest-reference` から再実行します。実行計画はJSON互換の構造として保存できます。

## 既存工程結果との互換性

既存の `config/pipeline/stage-result.schema.v1.json` は変更しません。`artifact_ref_from_stage_result()` が、検証済みのstage-result v1から型付き `ArtifactRef` を生成します。これにより既存実行器を破壊せずにDAGへ移行できます。

## 完了境界

この変更で完了するのは #139 のルート契約と #168 の成果物DAGです。`AvatarSpec`、`ConstructionSpec`、`FitSpec`、`MaterialSpec`、`StylingSpec`、`QualitySpec` の詳細ペイロードは、それぞれ #140〜#145 の完了条件に従います。

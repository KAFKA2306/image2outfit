# 黒猫ボンテージ衣装 制作計画

## 正準識別子

- product id: `siroino-black-cat-bondage`
- target: `SiroinoSotai_PC`
- issue: #200
- revision: `v1-parametric-black-cat-bondage`

## 13ステージ

1. **ingest-reference**: URL、受領時刻、SHA-256、非再配布を固定する。
2. **normalize-view**: 前方 `-Y`、上方 `+Z`、左右対称面 `X=0` とする。
3. **decompose-garment**: コルセット、レース、ハーネス、プリーツ、腰装飾、腕装備、猫耳、ガーターへ分解する。
4. **draft-patterns**: コルセット7パネル、プリーツ24枚、猫耳4三角形を数値化する。
5. **infer-stitches**: 構造縫合と装飾接続を分ける。
6. **initialize-3d**: SiroinoSotai_PC のトルソー、腰、腕、頭、大腿へ配置する。
7. **build-blender**: 決定論的スクリプトで材質と全構成要素を生成する。
8. **simulate-cloth**: 初回フィット後、スカートと布縁へ限定して適用する。
9. **skin-and-export**: 公式アーマチュアへウェイト転送し、FBXを出力する。
10. **render-evidence**: 5面と6ポーズをPNG/WebPで保存する。
11. **audit-geometry**: 貫通、非多様体、左右差、接続、プリーツ数を監査する。
12. **visual-review**: 参照とのシルエット、層序、素材差、装飾密度を直接確認する。
13. **finalize-candidate**: 全証拠をハッシュ化し、`COMPLETE` または `REJECTED` を決める。

## 初回PRの境界

初回PRは参照監査、要素分解、数値契約、Blender生成実装までをコミットする。生成画像とバイナリは Hosted Blender 実行後に回収・監査し、同じブランチへ追加コミットする。実行前に成功状態は記録しない。

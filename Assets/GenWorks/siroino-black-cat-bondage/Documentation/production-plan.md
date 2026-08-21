# 黒猫ボンテージ衣装 制作計画

## 正準識別子

- product id: `siroino-black-cat-bondage`
- target: `SiroinoSotai_PC`
- issue: #200
- PR: #204
- revision: `v4-cs-25-10300-reference-corrected`
- reference brand: `Malymoon`
- reference product: `スタッズレザーボンテージキャット`
- model code: `CS-25-10300`
- official URL: `https://www.malymoon-costume.com/view/item/000000004757`
- current private reference SHA-256: `4bf25fce6fb5a97d219ea024bf6c73d01d830f448c0d55a4a94f2dc6197e249b`
- source image redistribution: **false**

## 公式ページで確認した実物仕様

2026-08-09 に Malymoon 公式商品ページを一次情報として確認した。

- colorways: `ブラック`, `グレー`
- free size: トップス着丈34cm、バスト80cm、スカート着丈20cm、パンツ着丈23cm、ウエスト70cm
- material: ポリエステル90%、スパンデックス10%
- fabric: 伸縮性あり、透け感なし、裏地なし
- listed components:
  - ネコ耳カチューシャ
  - 首飾り
  - トップス
  - 二の腕飾り
  - アームカバー
  - アームベルト×6
  - パンツ
  - スカート
  - ウエストチェーン
  - 太もも飾り
  - 足首飾り
  - ニーハイソックス
  - しっぽ

商品ページ見出しの「13点」とカテゴリ表示の「14点」には公式サイト内で表記差があるため、制作契約では点数ではなく上記の明示された構成要素を正準とする。

## v4で実装する差分

1. v3の身体実測フィット済みコルセット、猫耳、ガントレット、大腿ガーターを維持する。
2. アームベルトを左右3本ずつ、合計6本へ修正する。
3. スカート下にパンツ層を追加する。
4. 左右のニーハイソックスを追加する。
5. 左右の足首飾りを追加する。
6. 腰後方へしっぽを追加する。
7. ウエストベルトへスタッズ列を追加する。
8. 同一ジオメトリで `black` / `gray` の2色Material Variantを `.blend` 内に保持する。
9. 技術監査へ `armBelts6 / pantsLayer / kneeHighSocks2 / ankleOrnaments2 / tail / officialColorways` を追加する。

## 13ステージ

1. **ingest-reference**: 公式URL、モデルコード、受領画像SHA-256、非再配布を固定する。
2. **normalize-view**: 前方 `-Y`、上方 `+Z`、左右対称面 `X=0` とする。
3. **decompose-garment**: 公式ページの明示構成要素へ分解する。
4. **draft-patterns**: コルセット、プリーツ、パンツ、ソックス、腕ベルト、猫耳、アクセサリを数値化する。
5. **infer-stitches**: 構造縫合と装飾接続を分ける。
6. **initialize-3d**: SiroinoSotai_PC のトルソー、腰、腕、頭、大腿、下腿へ配置する。
7. **build-blender**: 決定論的スクリプトで材質と全構成要素を生成する。
8. **fit-layers**: 体型に追従しつつ、トップス・パンツ・スカート・ソックスの層序を保つ。
9. **skin-and-export**: 既存アーマチュアへ割当し、FBXを出力する。
10. **render-evidence**: 5面と6ポーズをPNG/WebPで保存する。
11. **audit-geometry**: 貫通、非多様体、左右差、接続、構成要素数を監査する。
12. **visual-review**: 参照とのシルエット、層序、素材差、装飾密度を直接確認する。
13. **finalize-candidate**: 全証拠をハッシュ化し、`COMPLETE` または `REJECTED` を決める。

生成・比較・失敗レンダーは削除せず保存する。Unity / NDMF / VRChat runtime は実行されるまで `OUT_OF_SCOPE` とし、製品完成のブロッカーにはしない。

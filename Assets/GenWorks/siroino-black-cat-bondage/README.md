# Malymoon CS-25-10300 inspired outfit for SiroinoSotai_PC

`SiroinoSotai_PC` 向けに、Malymoon公式商品 **スタッズレザーボンテージキャット**（型番 `CS-25-10300`）を一次情報で同定し、その構成要素を再実行可能な Blender Python で再構築する製品ディレクトリです。現在状態は **WORKING** です。

公式商品ページ: `https://www.malymoon-costume.com/view/item/000000004757`

## v4 の制作内容

v3で直接レビュー後に修正した身体フィットを維持しつつ、公式商品ページに明示された実物セットへ寄せます。

- 身体曲面に沿う左右分割コルセット、アイレット、交差レース
- チョーカー、肩ストラップ、胸元ハーネス
- プリーツミニスカート
- スカート下のパンツ層
- 腰ベルト、リング、チェーン、スタッズ
- 二の腕飾り
- 左右アームカバー
- **アームベルト6本（左右3本ずつ）**
- 猫耳カチューシャ
- 左右太もも飾り
- 左右足首飾り
- 左右ニーハイソックス
- しっぽ
- `black` / `gray` の2色Material Variantを同一ジオメトリで保持
- 全メッシュの既存Siroino骨への明示的割当
- 5面レンダーと6ポーズレンダーの Hosted Blender 経路

## 公式ページで確認した寸法・素材

- フリーサイズ
- トップス着丈34cm
- バスト80cm
- スカート着丈20cm
- パンツ着丈23cm
- ウエスト70cm
- ポリエステル90%、スパンデックス10%
- 伸縮性あり、透け感なし、裏地なし

実寸値は人間用商品の情報であり、SiroinoSotai_PCへそのままメートル換算せず、シルエット・丈比率・層序の拘束条件として使います。

## 参照画像の扱い

現在のユーザー提供参照画像は SHA-256 `4bf25fce6fb5a97d219ea024bf6c73d01d830f448c0d55a4a94f2dc6197e249b` として provenance のみ保持します。画像本体、人物、ロゴ、透かしはリポジトリへ再配布しません。

## 実行

```bash
blender --background --factory-startup \
  --python tools/siroino_black_cat_bondage_product.py \
  -- --job config/products/siroino-black-cat-bondage/job.json

blender --background \
  Assets/GenWorks/siroino-black-cat-bondage/Source/Blender/SiroinoBlackCatBondage.blend \
  --python tools/siroino_black_cat_bondage_pose_render.py \
  -- --job config/products/siroino-black-cat-bondage/job.json
```

## 技術監査

v4では従来のコルセット・猫耳・ガントレット・大腿ガーター・5面に加え、`armBelts6`、`pantsLayer`、`kneeHighSocks2`、`ankleOrnaments2`、`tail`、`officialColorways` を自動監査します。

## 完了ゲート

Hosted Blenderで現行v4を生成した後、5面、6ポーズ、構成要素、ボーン割当、素体貫通、リング／チェーン／しっぽの接続、参照とのシルエットを直接確認します。生成・比較・失敗レンダーはGitへ保存します。

Unity import、NDMF、VRChat Build & Test、VRChat runtimeは `OUT_OF_SCOPE` です。

Issue: #200  
PR: #204

# Black Cat Bondage Outfit for SiroinoSotai_PC

`SiroinoSotai_PC` 向けの黒猫モチーフ衣装を、再実行可能な Blender Python で構築する製品ディレクトリです。現在状態は **WORKING** です。

## v2 の制作内容

- 身体曲面に沿う分割コルセット、背面パネル、左右カップ
- 14個のアイレットと交差レース
- チョーカー、肩ストラップ、胸元ハーネス
- 24枚の独立した放射状プリーツ
- 腰ベルト、6個のリング、5本のチェーン
- 上腕バンド、前腕方向へ沿わせたガントレット
- 頭部へ追従する猫耳ヘッドバンド
- 左右の大腿ガーターとチェーン
- 全メッシュの明示的なボーン割当と Armature modifier
- 5面レンダーと6ポーズレンダーの Hosted Blender 経路

## 参照画像の扱い

参照画像本体はリポジトリへ収録しません。Gitには、画像内表示URLとSHA-256 `c5261b8740daafa4041ed3ffba67b6cac2dafdc386cbfe41d67ce4679714cf5c`だけを保存します。人物の顔、髪、身体、ロゴ、透かしは制作対象外です。

## 実行

```bash
blender --background --factory-startup \
  --python tools/siroino_black_cat_bondage_v2_product.py \
  -- --job config/products/siroino-black-cat-bondage/job.json

blender --background \
  Assets/GenWorks/siroino-black-cat-bondage/Source/Blender/SiroinoBlackCatBondage.blend \
  --python tools/siroino_black_cat_bondage_pose_render.py \
  -- --job config/products/siroino-black-cat-bondage/job.json
```

## 完了ゲート

5面、6ポーズ、ボーン割当、構成要素数、直接の見た目、素体貫通を確認し、生成・比較・失敗レンダーをGitへ保存してからリリース判定します。Unity import、NDMF、VRChat Build & Test、VRChat runtimeは実行されるまで `OUT_OF_SCOPE` のままです。

Issue: #200  
PR: #201

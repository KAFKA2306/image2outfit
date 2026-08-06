# Black Cat Bondage Outfit for SiroinoSotai_PC

`SiroinoSotai_PC` 向けの黒猫モチーフ衣装を、再実行可能な Blender Python で構築する作業ディレクトリです。状態は **WORKING** です。未実行の成果物を完成扱いにはしません。

## 現在の実装

- パネル分割したクロップド・コルセットと上部カップ
- 14個のアイレットと交差レース
- チョーカー、肩ストラップ、胸元ハーネス
- 24枚の独立した放射状プリーツ
- 腰ベルト、6個の金属リング、5本のチェーン
- 上腕バンド、長いガントレット、装飾ストラップ
- 猫耳ヘッドバンド
- 左右の大腿ガーターとチェーン
- `.blend`、FBX、front preview、build report を生成する Blender entrypoint

## 参照画像の扱い

参照画像はリポジトリへ収録しません。Git には、画像内に表示されたURLと SHA-256 `c5261b8740daafa4041ed3ffba67b6cac2dafdc386cbfe41d67ce4679714cf5c` だけを保存します。参照先URLは Issue 作成時に実行環境から到達できなかったため、商品名や仕様の外部検証には使用していません。

## 実行

```bash
blender --background --factory-startup \
  --python tools/siroino_black_cat_bondage_product.py \
  -- --job config/products/siroino-black-cat-bondage/job.json
```

GitHub Actions では `.github/workflows/build-product-hosted.yml` がこの job を検出して実行します。

## 生成先

- Blender: `Source/Blender/SiroinoBlackCatBondage.blend`
- FBX: `Models/SiroinoBlackCatBondage.fbx`
- 初回画像: `Previews/front.png`
- 実行報告: `Evidence/Build/product-build-report.json`

## 完了ゲート

front / back / left / right / three-quarter の5面、neutralを含む6ポーズ、素体貫通監査、ウェイト監査、Unity Prefab / Modular Avatar 宣言、直接の見た目監査が揃うまでは `COMPLETE` にしません。失敗レンダーも `Evidence/Rejected` に残します。

Issue: #200

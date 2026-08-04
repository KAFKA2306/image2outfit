# Nocturne Angel Modular Set for Siroino

`WORKING` — user-supplied reference imageから、SiroinoSotai_PC向けの黒・ベージュ・白のモジュール式衣装を独立生成する製品ワークスペースです。参照画像自体は再配布しません。

## 現在のrevision

`v3-sewn-v-neck-stable-modules`

- 前左・前右・背面・左右脇の5型紙身頃
- V字ネック、肩ストラップ、明示的アームホール
- 狭い3分割セーラー襟
- Blender 4.4 Clothを32フレーム実行した8段スカート
- Clothベイク後のスカート、裾、腰帯は腰ボーンへ安定追従
- レッグウォーマーは下腿、靴は足、翼とチャームは所定ボーンへ剛体追従
- 丸い輪郭の積層羽根
- 最大4ボーン影響、非ウェイト頂点禁止

v1とv2の実レンダリングは直接画像監査で却下し、`Tests/visual-review-v1.json` と `Tests/visual-review-v2.json` に保持しています。v3のBlender生成、5面、必須6ポーズ、直接画像監査が完了するまで `COMPLETE` ではありません。Unity、Modular Avatar、NDMF、VRChat runtimeは `OUT_OF_SCOPE` です。

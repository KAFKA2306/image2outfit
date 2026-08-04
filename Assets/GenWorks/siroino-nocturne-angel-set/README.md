# Nocturne Angel Modular Set for Siroino

`WORKING` — user-supplied reference imageから、SiroinoSotai_PC向けの黒・ベージュ・白のモジュール式衣装を独立生成する製品ワークスペースです。参照画像自体は再配布しません。

## 現在のrevision

`v4-clearance-articulated-silhouette`

- 幅と奥行きを縮めた前左・前右・背面・左右脇の5型紙身頃
- V字ネック、肩ストラップ、明示的アームホール
- 身体トポロジーを複製せず、評価済み身体表面を衝突制約として使う外向きクリアランス補正
- Blender 4.4 Clothを32フレーム実行する8段スカート
- スカートと裾は腰から左右大腿へ連続的にブレンドして座位・屈曲へ追従
- パフ袖は上腕、アームウォーマーとカフは前腕、レッグウォーマーは下腿、靴は足へ部位別追従
- 翼を左右3枚の丸い羽根へ整理し、パネルと羽根はFBX出力前に明示三角形化
- 最大4ボーン影響、非ウェイト頂点禁止、退化三角形ゼロを維持

v1、v2、v3の実レンダリングは直接画像監査で却下し、それぞれの`Tests/visual-review-v*.json`に保持しています。v4のBlender生成、5面、必須6ポーズ、直接画像監査が完了するまで`COMPLETE`ではありません。Unity、Modular Avatar、NDMF、VRChat runtimeは`OUT_OF_SCOPE`です。

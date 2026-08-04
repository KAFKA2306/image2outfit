# Nocturne Angel Modular Set for Siroino

`WORKING` — user-supplied reference imageから、SiroinoSotai_PC向けの黒・ベージュ・白のモジュール式衣装を独立生成する製品ワークスペースです。参照画像自体は再配布しません。

## 現在のrevision

`v5-skinweighted-pleated-volume`

- 胴体周方向へ配置した前左・前右・背面・左右脇の5型紙身頃
- V字ネックとアームホールを維持し、評価済み身体頂点から最大4影響のウェイトを転送
- 12本の放射状プリーツを持つ短いスカート
- Blender 4.4 Clothを32フレーム実行し、重力影響を0.18へ抑え、張力・圧縮・せん断・曲げ剛性でプリーツ形状を保持
- 袖、アームウォーマー、カフ、レッグウォーマー、靴にも身体ウェイトを転送
- 身体トポロジーは複製せず、評価済み身体表面を外向きクリアランス制約としてのみ利用
- 翼は平板を廃止し、左右4枚の体積を持つ楕円体羽根へ変更
- 浮遊していた帽子と耳を頭部ボーン始点側へ下げる
- 最大4ボーン影響、非ウェイト頂点禁止、ウェイト総和誤差ゼロ、退化三角形ゼロを維持

v1からv4までの実レンダリングは直接画像監査で却下し、それぞれの`Tests/visual-review-v*.json`に保持しています。v5のBlender生成、5面、必須6ポーズ、直接画像監査が完了するまで`COMPLETE`ではありません。Unity、Modular Avatar、NDMF、VRChat runtimeは`OUT_OF_SCOPE`です。

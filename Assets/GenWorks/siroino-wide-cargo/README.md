# Siroino Wide Cargo

`Assets/GenWorks/siroino-wide-cargo/ProductManifest.json`

`config/genworks-handoff-policy.json`

SiroinoSotai v1.0向けのロゴなしWide Cargo衣装です。現在の衣装メッシュは1,168頂点、2,040三角形、1頂点あたり最大3ボーン影響です。

## 現在の状態

製品は7件のrepository完了条件のうち6件を満たし、`WORKING`です。

現在PASSしているもの:

- Blenderでの形状生成
- 編集可能な`.blend`
- FBX書き出し
- 衣装Prefabの宣言
- 5方向レンダリング証拠
- ポーズレンダリング証拠

残る完了条件は `visualAppearanceReview` だけです。

2026-08-29に、main commit `a2691970b22cf7d2b135d6c9582b985e4a22a1c8` からReview Console workflow run `33257472164` が生成したGitHub Pages artifactを直接確認しました。5方向レンダリングでは、腰回りが別部品の筒のように見えること、脚部が円筒に近く衣服らしい形状変化が乏しいこと、カーゴポケットが硬い直方体に見えることを確認しています。このため現在revisionの `visualAppearanceReview` は `FAIL` のままです。

ファイルが存在することや自動の形状監査PASSだけでは、この外観判定をPASSにしません。

Unity import/save/reload、Modular Avatar/NDMF processing、VRChat Build & Test、VRChat runtimeは `config/genworks-handoff-policy.json` ではrepository `COMPLETE` の対象外です。これらは引き続き未検証であり、UnityまたはVRChatで実行した証拠なしに対応済みとは扱いません。

## Tracked asset

正本の衣装Prefab:

`Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoWideCargo.prefab`

宣言されている統合Prefab `Assets/GenWorks/siroino-wide-cargo/Prefab/SiroinoSotai_WideCargo.prefab` は現在repositoryに存在しません。そのため、現行成果物をドラッグ&ドロップでアバター統合済みとは扱いません。

Modular Avatarで衣装を設定する場合は、repository独自処理ではなく公式の `Setup Outfit` / `Merge Armature` を使用します。

https://modular-avatar.nadena.dev/docs/tutorials/clothing

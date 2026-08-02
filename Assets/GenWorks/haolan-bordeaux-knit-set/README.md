# Bordeaux Rib Knit Set for HAOLAN v1.6

HAOLAN v1.6向けのボルドー色リブニット衣装です。旧候補は `Assets/GenWorks/Legacy/Snapshots/haolan/bordeaux-knit-set-candidate` に保存されていますが、現在の作業・検証・引き継ぎはこのディレクトリだけを正規状態として扱います。

## 正規パス

```text
config/products/haolan-bordeaux-knit-set/
  job.json
  license.json

Assets/GenWorks/haolan-bordeaux-knit-set/
  ProductManifest.json
  README.md
  Source/Blender/HAOLAN_BordeauxKnitSet.blend
  Models/HAOLAN_BordeauxKnitSet.fbx
  Prefab/HAOLAN_BordeauxKnitSet.prefab
  Prefab/HAOLAN_Lowpoly_BordeauxKnitSet.prefab
  Previews/
```

## 現在の判定

**NO-GO / WORKING**

旧候補では静的な形状・ウェイト・FBX構造・Prefab GUID・独立ジオメトリ往復検証が通過しています。ただし、それだけでは現行の完成条件を満たしません。正規パス上のBlender/FBX生成、Unity 2022.3.22f1でのインポートとPrefab保存・再読込、Modular Avatar/NDMF、実5方向レンダリング、必須ポーズ、VRChat実行、人間による外観確認を改めて実施します。

## 成果物

- 編集可能なBlenderソース
- HAOLANスケルトンへウェイト済みのFBX
- 衣装単体Prefab
- HAOLAN統合Prefab
- front / back / left / right / three-quarter の実レンダリング
- neutral / arms-up / arm-cross / crouch / sit / prone のポーズ検証
- multiviewおよびpose-review WebP
- ハッシュを含むプレビューマニフェスト
- `ProductManifest.json` に記録された技術ゲートと残課題

## ライセンス境界

HAOLAN本体のFBX・Prefab・テクスチャ等はリポジトリへ再配布しません。セルフホスト環境に存在する正規購入・取得済みソースを検証時だけ参照します。衣装配布時は `HAOLAN by かなﾘぁさんち` のクレジットを保持します。

## 実行

```powershell
task candidate JOB=config/products/haolan-bordeaux-knit-set/job.json
task audit:genworks
task audit:repo
task check:python
```

`RELEASED` へ昇格できるのは、同一候補の全技術ゲートと人間による外観・ポーズ・VRChat実行確認が通過した場合だけです。

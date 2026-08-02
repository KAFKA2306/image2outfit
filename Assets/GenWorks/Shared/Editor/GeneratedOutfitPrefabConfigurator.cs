#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Linq;
using nadena.dev.modular_avatar.core;
using UnityEditor;
using UnityEngine;

namespace Image2Outfit.Editor
{
    /// <summary>
    /// Makes every generated outfit prefab install-ready for Modular Avatar.
    /// The prefab asset is configured directly, so Setup Outfit does not need
    /// to be invoked while the outfit is already parented under an avatar.
    /// </summary>
    [InitializeOnLoad]
    internal static class GeneratedOutfitPrefabConfigurator
    {
        private const string ProductRoot = "Assets/GenWorks";
        private const string OutfitPrefabSegment = "/Prefabs/Outfit/";
        private const string GeneratedArmatureSuffix = ".1";

        private static readonly HashSet<string> PendingPaths =
            new HashSet<string>(StringComparer.Ordinal);

        private static bool running;
        private static bool delayedRunQueued;

        static GeneratedOutfitPrefabConfigurator()
        {
            EditorApplication.delayCall += ConfigureAllGeneratedPrefabs;
        }

        [MenuItem("Tools/Image2Outfit/Configure Generated Modular Avatar Prefabs")]
        internal static void ConfigureAllGeneratedPrefabs()
        {
            var paths = AssetDatabase.FindAssets("t:Prefab", new[] { ProductRoot })
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(IsGeneratedOutfitPrefab)
                .OrderBy(path => path, StringComparer.Ordinal)
                .ToArray();

            ConfigurePaths(paths, true);
        }

        internal static void QueueImportedAssets(IEnumerable<string> paths)
        {
            foreach (var path in paths.Where(IsGeneratedOutfitPrefab))
                PendingPaths.Add(path);

            if (PendingPaths.Count == 0 || delayedRunQueued)
                return;

            delayedRunQueued = true;
            EditorApplication.delayCall += ConfigurePendingPrefabs;
        }

        private static void ConfigurePendingPrefabs()
        {
            delayedRunQueued = false;
            var paths = PendingPaths.OrderBy(path => path, StringComparer.Ordinal).ToArray();
            PendingPaths.Clear();
            ConfigurePaths(paths, false);
        }

        private static void ConfigurePaths(IEnumerable<string> paths, bool logSummary)
        {
            if (running)
            {
                foreach (var path in paths.Where(IsGeneratedOutfitPrefab))
                    PendingPaths.Add(path);
                return;
            }

            running = true;
            var changedCount = 0;
            var failedCount = 0;
            try
            {
                foreach (var path in paths.Distinct(StringComparer.Ordinal))
                {
                    try
                    {
                        if (ConfigurePrefab(path))
                            changedCount++;
                    }
                    catch (Exception exception)
                    {
                        failedCount++;
                        Debug.LogError(
                            $"[Image2Outfit] Modular Avatar prefab configuration failed: {path}\n{exception}"
                        );
                    }
                }

                if (changedCount > 0)
                    AssetDatabase.SaveAssets();
            }
            finally
            {
                running = false;
            }

            if (logSummary)
            {
                Debug.Log(
                    $"[Image2Outfit] Generated Modular Avatar prefabs: "
                    + $"changed={changedCount}, failed={failedCount}"
                );
            }
        }

        private static bool ConfigurePrefab(string assetPath)
        {
            if (!IsGeneratedOutfitPrefab(assetPath))
                return false;

            var root = PrefabUtility.LoadPrefabContents(assetPath);
            try
            {
                bool changed;
                string error;
                if (!TryConfigure(root, out changed, out error))
                    throw new InvalidOperationException(error);

                if (!changed)
                    return false;

                var saved = PrefabUtility.SaveAsPrefabAsset(root, assetPath);
                if (saved == null)
                    throw new InvalidOperationException("Prefab asset could not be saved");

                Debug.Log($"[Image2Outfit] Added Modular Avatar contract: {assetPath}");
                return true;
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }

        internal static bool TryConfigure(
            GameObject outfitRoot,
            out bool changed,
            out string error
        )
        {
            changed = false;
            error = null;

            if (outfitRoot == null)
            {
                error = "Outfit root is null";
                return false;
            }

            var renderers = outfitRoot.GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .Where(renderer => renderer.sharedMesh != null)
                .ToArray();
            if (renderers.Length == 0)
            {
                error = "Generated outfit prefab has no skinned mesh renderer";
                return false;
            }
            if (renderers.Any(renderer => renderer.rootBone == null))
            {
                error = "Generated outfit prefab contains a skinned mesh without a root bone";
                return false;
            }

            var armatures = renderers
                .Select(renderer => FindArmatureRoot(outfitRoot.transform, renderer.rootBone))
                .Distinct()
                .ToArray();
            if (armatures.Any(armature => armature == null) || armatures.Length != 1)
            {
                error = "Generated outfit renderers must share one armature directly below the prefab root";
                return false;
            }

            var armatureRoot = armatures[0];
            var merge = armatureRoot.GetComponent<ModularAvatarMergeArmature>();
            var targetArmaturePath = merge == null || merge.mergeTarget == null
                ? null
                : merge.mergeTarget.referencePath;

            if (string.IsNullOrWhiteSpace(targetArmaturePath))
            {
                targetArmaturePath = RemoveGeneratedSuffix(armatureRoot.name);
                var generatedArmatureName = targetArmaturePath + GeneratedArmatureSuffix;
                if (!string.Equals(armatureRoot.name, generatedArmatureName, StringComparison.Ordinal))
                {
                    armatureRoot.name = generatedArmatureName;
                    changed = true;
                }
            }

            if (merge == null)
            {
                merge = armatureRoot.gameObject.AddComponent<ModularAvatarMergeArmature>();
                changed = true;
            }
            if (merge.mergeTarget == null
                || !string.Equals(
                    merge.mergeTarget.referencePath,
                    targetArmaturePath,
                    StringComparison.Ordinal
                ))
            {
                merge.mergeTarget = new AvatarObjectReference
                {
                    referencePath = targetArmaturePath
                };
                changed = true;
            }
            if (merge.LockMode != ArmatureLockMode.BaseToMerge)
            {
                merge.LockMode = ArmatureLockMode.BaseToMerge;
                changed = true;
            }
            if (!merge.mangleNames)
            {
                merge.mangleNames = true;
                changed = true;
            }

            string[] targetRootBonePaths;
            try
            {
                targetRootBonePaths = renderers
                    .Select(renderer => BuildTargetPath(
                        armatureRoot,
                        renderer.rootBone,
                        targetArmaturePath
                    ))
                    .Distinct(StringComparer.Ordinal)
                    .ToArray();
            }
            catch (InvalidOperationException exception)
            {
                error = exception.Message;
                return false;
            }

            if (targetRootBonePaths.Length != 1)
            {
                error = "Generated outfit renderers must share one Modular Avatar root-bone target";
                return false;
            }

            var settings = outfitRoot.GetComponent<ModularAvatarMeshSettings>();
            if (settings == null)
            {
                settings = outfitRoot.AddComponent<ModularAvatarMeshSettings>();
                changed = true;
            }

            if (settings.InheritProbeAnchor != ModularAvatarMeshSettings.InheritMode.SetOrInherit)
            {
                settings.InheritProbeAnchor = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
                changed = true;
            }
            if (settings.InheritBounds != ModularAvatarMeshSettings.InheritMode.SetOrInherit)
            {
                settings.InheritBounds = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
                changed = true;
            }

            var targetRootBonePath = targetRootBonePaths[0];
            if (settings.ProbeAnchor == null
                || !string.Equals(
                    settings.ProbeAnchor.referencePath,
                    targetRootBonePath,
                    StringComparison.Ordinal
                ))
            {
                settings.ProbeAnchor = new AvatarObjectReference
                {
                    referencePath = targetRootBonePath
                };
                changed = true;
            }
            if (settings.RootBone == null
                || !string.Equals(
                    settings.RootBone.referencePath,
                    targetRootBonePath,
                    StringComparison.Ordinal
                ))
            {
                settings.RootBone = new AvatarObjectReference
                {
                    referencePath = targetRootBonePath
                };
                changed = true;
            }

            var bounds = renderers[0].localBounds;
            if (!settings.Bounds.Equals(bounds))
            {
                settings.Bounds = bounds;
                changed = true;
            }

            return true;
        }

        private static Transform FindArmatureRoot(Transform outfitRoot, Transform bone)
        {
            var current = bone;
            while (current != null && current.parent != outfitRoot)
                current = current.parent;
            return current;
        }

        private static string BuildTargetPath(
            Transform armatureRoot,
            Transform bone,
            string targetArmaturePath
        )
        {
            if (bone == armatureRoot)
                return targetArmaturePath;

            var segments = new Stack<string>();
            var current = bone;
            while (current != null && current != armatureRoot)
            {
                segments.Push(current.name);
                current = current.parent;
            }

            if (current != armatureRoot)
                throw new InvalidOperationException("A renderer root bone is outside the generated armature");

            return targetArmaturePath + "/" + string.Join("/", segments.ToArray());
        }

        private static string RemoveGeneratedSuffix(string name)
        {
            return name.EndsWith(GeneratedArmatureSuffix, StringComparison.Ordinal)
                ? name.Substring(0, name.Length - GeneratedArmatureSuffix.Length)
                : name;
        }

        private static bool IsGeneratedOutfitPrefab(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return false;

            var normalized = path.Replace('\\', '/');
            return normalized.StartsWith(ProductRoot + "/", StringComparison.Ordinal)
                && normalized.IndexOf(OutfitPrefabSegment, StringComparison.Ordinal) >= 0
                && normalized.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase);
        }
    }

    internal sealed class GeneratedOutfitPrefabPostprocessor : AssetPostprocessor
    {
        private static void OnPostprocessAllAssets(
            string[] importedAssets,
            string[] deletedAssets,
            string[] movedAssets,
            string[] movedFromAssetPaths
        )
        {
            GeneratedOutfitPrefabConfigurator.QueueImportedAssets(
                importedAssets.Concat(movedAssets)
            );
        }
    }
}
#endif

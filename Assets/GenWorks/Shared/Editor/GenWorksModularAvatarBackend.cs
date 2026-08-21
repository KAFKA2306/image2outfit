#if UNITY_EDITOR
using System;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace GenWorks.Editor
{
    internal static class GenWorksModularAvatarBackend
    {
        private const string MergeArmatureTypeName =
            "nadena.dev.modular_avatar.core.ModularAvatarMergeArmature";

        internal static bool IsAvailable => FindMergeArmatureType() != null;

        internal static GameObject Apply(
            GameObject avatar,
            GameObject mergeTarget,
            GameObject outfitPrefab
        )
        {
            if (avatar == null)
                throw new ArgumentNullException(nameof(avatar));
            if (mergeTarget == null)
                throw new ArgumentNullException(nameof(mergeTarget));
            if (outfitPrefab == null)
                throw new ArgumentNullException(nameof(outfitPrefab));
            if (EditorUtility.IsPersistent(avatar))
                throw new InvalidOperationException(
                    "Select an avatar instance in an open Scene, not a prefab asset."
                );
            if (
                mergeTarget != avatar
                && !mergeTarget.transform.IsChildOf(avatar.transform)
            )
                throw new InvalidOperationException(
                    "Merge Target must be the selected avatar or one of its children."
                );
            if (!PrefabUtility.IsPartOfPrefabAsset(outfitPrefab))
                throw new InvalidOperationException(
                    "The selected outfit path does not resolve to a prefab asset."
                );

            var mergeType = FindMergeArmatureType();
            if (mergeType == null)
                throw new InvalidOperationException(
                    "Modular Avatar is not loaded. Resolve the VPM packages before applying an outfit."
                );

            var instance = PrefabUtility.InstantiatePrefab(outfitPrefab, avatar.scene)
                as GameObject;
            if (instance == null)
                throw new InvalidOperationException("Failed to instantiate the outfit prefab.");

            Undo.RegisterCreatedObjectUndo(instance, "Apply GenWorks outfit");
            Undo.SetTransformParent(
                instance.transform,
                avatar.transform,
                "Parent GenWorks outfit"
            );
            Undo.RecordObject(instance.transform, "Reset GenWorks outfit transform");
            instance.transform.localPosition = Vector3.zero;
            instance.transform.localRotation = Quaternion.identity;
            instance.transform.localScale = Vector3.one;

            var component = instance
                .GetComponentsInChildren<Component>(true)
                .FirstOrDefault(candidate =>
                    candidate != null && mergeType.IsInstanceOfType(candidate)
                );
            if (component == null)
            {
                var mergeHost = FindSourceArmature(instance);
                component = Undo.AddComponent(mergeHost, mergeType);
            }

            ConfigureMergeTarget(component, mergeType, mergeTarget);
            Selection.activeGameObject = instance;
            EditorGUIUtility.PingObject(instance);
            return instance;
        }

        private static GameObject FindSourceArmature(GameObject outfit)
        {
            var renderer = outfit
                .GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .FirstOrDefault(candidate => candidate != null && candidate.rootBone != null);
            if (renderer != null)
            {
                var rootBone = renderer.rootBone;
                var parent = rootBone.parent;
                if (
                    parent != null
                    && parent != outfit.transform
                    && parent.IsChildOf(outfit.transform)
                )
                    return parent.gameObject;
                if (rootBone.IsChildOf(outfit.transform))
                    return rootBone.gameObject;
            }

            var namedArmature = outfit
                .GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(transform =>
                    transform != outfit.transform
                    && string.Equals(
                        transform.name,
                        "Armature",
                        StringComparison.OrdinalIgnoreCase
                    )
                );
            return namedArmature != null ? namedArmature.gameObject : outfit;
        }

        private static void ConfigureMergeTarget(
            Component component,
            Type mergeType,
            GameObject mergeTarget
        )
        {
            var field = mergeType.GetField(
                "mergeTarget",
                BindingFlags.Public | BindingFlags.Instance
            );
            if (field == null)
                throw new MissingFieldException(mergeType.FullName, "mergeTarget");

            var reference = field.GetValue(component);
            if (reference == null)
                throw new InvalidOperationException(
                    "Modular Avatar mergeTarget reference was not initialized."
                );

            var setMethod = reference
                .GetType()
                .GetMethod(
                    "Set",
                    BindingFlags.Public | BindingFlags.Instance,
                    null,
                    new[] { typeof(GameObject) },
                    null
                );
            if (setMethod == null)
                throw new MissingMethodException(reference.GetType().FullName, "Set(GameObject)");

            Undo.RecordObject(component, "Configure Modular Avatar merge target");
            setMethod.Invoke(reference, new object[] { mergeTarget });
            EditorUtility.SetDirty(component);
        }

        private static Type FindMergeArmatureType()
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var type = assembly.GetType(MergeArmatureTypeName, false);
                if (type != null)
                    return type;
            }
            return null;
        }
    }
}
#endif

#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using nadena.dev.modular_avatar.core;
using UnityEditor;
using UnityEngine;
using VRC.SDK3A.Editor;
using VRC.SDKBase.Editor;

namespace Image2Outfit.Editor
{
    public static class Pipeline
    {
        [Serializable]
        private sealed class Job
        {
            public string id;
            public string productName;
            public string fbxAssetPath;
            public string prefabAssetPath;
            public string integratedPrefabAssetPath;
            public string targetAvatarAssetPath;
            public string artifactDir;
            public string[] allowedExtraBones;
        }

        [Serializable]
        private sealed class Metrics
        {
            public int meshRenderers;
            public int vertices;
            public int triangles;
            public int materialSlots;
            public int blendShapes;
            public int bones;
            public int nonFiniteValues;
            public int degenerateTriangles;
            public int missingMaterials;
            public int missingBones;
            public int unweightedVertices;
            public int weightSumErrors;
            public int missingScripts;
        }

        [Serializable]
        private sealed class Report
        {
            public bool passed;
            public bool targetValidated;
            public bool buildAndTestPassed;
            public string unityVersion;
            public string prefabAssetPath;
            public string integratedPrefabAssetPath;
            public Metrics metrics = new Metrics();
            public List<string> errors = new List<string>();
            public List<string> warnings = new List<string>();
        }

        [Serializable]
        private sealed class BuildTestReport
        {
            public string status;
            public string checkedAt;
            public bool passed;
            public string unityVersion;
            public string combinedPrefabAssetPath;
            public string builderType;
            public string buildState;
            public string error;
        }

        public static void Run()
        {
            try
            {
                var jobPath = GetArgument("-image2outfitJob");
                if (string.IsNullOrWhiteSpace(jobPath))
                    throw new ArgumentException("-image2outfitJob is required");

                var job = JsonUtility.FromJson<Job>(File.ReadAllText(jobPath));
                if (job == null)
                    throw new InvalidDataException("job.json could not be parsed");

                var report = Execute(job);
                WriteReport(job, report);
                if (report.passed)
                {
                    EditorApplication.delayCall += () => FinishRun(job, report);
                    return;
                }

                var buildTest = new BuildTestReport
                {
                    status = "FAIL",
                    checkedAt = DateTime.UtcNow.ToString("O"),
                    passed = false,
                    unityVersion = Application.unityVersion,
                    combinedPrefabAssetPath = job.integratedPrefabAssetPath,
                    error = "static integration gate failed"
                };
                report.buildAndTestPassed = false;
                WriteBuildTestReport(job, buildTest);
                WriteReport(job, report);
                EditorApplication.Exit(2);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                EditorApplication.Exit(1);
            }
        }

        private static async void FinishRun(Job job, Report report)
        {
            try
            {
                var buildTest = await RunBuildAndTest(job);
                report.buildAndTestPassed = buildTest.passed;
                report.passed = report.passed && buildTest.passed;
                WriteBuildTestReport(job, buildTest);
                WriteReport(job, report);
                EditorApplication.Exit(report.passed ? 0 : 2);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                EditorApplication.Exit(1);
            }
        }

        private static Report Execute(Job job)
        {
            var report = new Report
            {
                unityVersion = Application.unityVersion,
                prefabAssetPath = job.prefabAssetPath,
                integratedPrefabAssetPath = job.integratedPrefabAssetPath
            };

            RequireAssetPath(job.fbxAssetPath, nameof(job.fbxAssetPath));
            RequireAssetPath(job.prefabAssetPath, nameof(job.prefabAssetPath));
            RequireAssetPath(job.integratedPrefabAssetPath, nameof(job.integratedPrefabAssetPath));
            RequireAssetPath(job.targetAvatarAssetPath, nameof(job.targetAvatarAssetPath));

            var importer = AssetImporter.GetAtPath(job.fbxAssetPath) as ModelImporter;
            if (importer == null)
            {
                report.errors.Add("FBX ModelImporter not found");
                return report;
            }

            var originalReadable = importer.isReadable;
            if (!originalReadable)
            {
                importer.isReadable = true;
                importer.SaveAndReimport();
            }
            else
            {
                AssetDatabase.ImportAsset(job.fbxAssetPath, ImportAssetOptions.ForceUpdate);
            }

            try
            {
                var model = AssetDatabase.LoadAssetAtPath<GameObject>(job.fbxAssetPath);
                if (model == null)
                {
                    report.errors.Add("FBX root GameObject not found");
                    return report;
                }

                ValidateHierarchy(model, report);
                ValidateMeshes(model, report);

                if (!report.errors.Any())
                    CreatePrefab(model, job.prefabAssetPath, report);

                ValidateTarget(model, job, report);
                if (!report.errors.Any())
                    CreateIntegratedPrefab(job, report);
                report.passed =
                    !report.errors.Any()
                    && report.targetValidated
                    && AssetDatabase.LoadAssetAtPath<GameObject>(job.prefabAssetPath) != null
                    && AssetDatabase.LoadAssetAtPath<GameObject>(job.integratedPrefabAssetPath) != null;
                return report;
            }
            finally
            {
                if (!originalReadable)
                {
                    importer = AssetImporter.GetAtPath(job.fbxAssetPath) as ModelImporter;
                    if (importer != null)
                    {
                        importer.isReadable = false;
                        importer.SaveAndReimport();
                    }
                }
                AssetDatabase.SaveAssets();
            }
        }

        private static void ValidateHierarchy(GameObject root, Report report)
        {
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                var scale = transform.localScale;
                if (!Finite(scale.x) || !Finite(scale.y) || !Finite(scale.z))
                    report.errors.Add($"non-finite transform: {GetPath(transform)}");
                if (scale.x <= 0f || scale.y <= 0f || scale.z <= 0f)
                    report.errors.Add($"non-positive scale: {GetPath(transform)}");
            }

            foreach (var gameObject in root.GetComponentsInChildren<Transform>(true).Select(x => x.gameObject))
                report.metrics.missingScripts += GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(gameObject);

            if (report.metrics.missingScripts > 0)
                report.errors.Add("missing MonoBehaviour scripts");
        }

        private static void ValidateMeshes(GameObject root, Report report)
        {
            var renderers = root.GetComponentsInChildren<Renderer>(true);
            report.metrics.meshRenderers = renderers.Length;

            foreach (var renderer in renderers)
            {
                report.metrics.materialSlots += renderer.sharedMaterials.Length;
                report.metrics.missingMaterials += renderer.sharedMaterials.Count(material => material == null);
            }

            foreach (var filter in root.GetComponentsInChildren<MeshFilter>(true))
            {
                if (filter.sharedMesh == null)
                {
                    report.errors.Add($"missing MeshFilter mesh: {GetPath(filter.transform)}");
                    continue;
                }
                ValidateMesh(filter.sharedMesh, false, null, report);
            }

            foreach (var renderer in root.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (renderer.sharedMesh == null)
                {
                    report.errors.Add($"missing skinned mesh: {GetPath(renderer.transform)}");
                    continue;
                }

                report.metrics.bones += renderer.bones.Length;
                report.metrics.missingBones += renderer.bones.Count(bone => bone == null);
                ValidateMesh(renderer.sharedMesh, true, renderer.bones, report);
            }

            if (report.metrics.meshRenderers == 0)
                report.errors.Add("no mesh renderer");
            if (report.metrics.missingMaterials > 0)
                report.errors.Add("missing material references");
            if (report.metrics.missingBones > 0)
                report.errors.Add("missing bone references");
            if (report.metrics.nonFiniteValues > 0)
                report.errors.Add("non-finite mesh values");
            if (report.metrics.degenerateTriangles > 0)
                report.errors.Add("degenerate triangles");
            if (report.metrics.unweightedVertices > 0)
                report.errors.Add("unweighted skinned vertices");
            if (report.metrics.weightSumErrors > 0)
                report.errors.Add("vertex weight sums outside tolerance");
        }

        private static void ValidateMesh(
            Mesh mesh,
            bool skinned,
            Transform[] rendererBones,
            Report report)
        {
            var vertices = mesh.vertices;
            var uv = mesh.uv;
            var triangles = mesh.triangles;

            report.metrics.vertices += vertices.Length;
            report.metrics.triangles += triangles.Length / 3;
            report.metrics.blendShapes += mesh.blendShapeCount;

            foreach (var vertex in vertices)
            {
                if (!Finite(vertex.x) || !Finite(vertex.y) || !Finite(vertex.z))
                    report.metrics.nonFiniteValues++;
            }

            foreach (var coordinate in uv)
            {
                if (!Finite(coordinate.x) || !Finite(coordinate.y))
                    report.metrics.nonFiniteValues++;
            }

            for (var index = 0; index + 2 < triangles.Length; index += 3)
            {
                var a = vertices[triangles[index]];
                var b = vertices[triangles[index + 1]];
                var c = vertices[triangles[index + 2]];
                if (Vector3.Cross(b - a, c - a).sqrMagnitude <= 1e-20f)
                    report.metrics.degenerateTriangles++;
            }

            if (!skinned)
                return;

            var weights = mesh.boneWeights;
            if (weights.Length != vertices.Length)
            {
                report.errors.Add($"bone weight count mismatch: {mesh.name}");
                return;
            }

            foreach (var weight in weights)
            {
                var values = new[] { weight.weight0, weight.weight1, weight.weight2, weight.weight3 };
                var positive = values.Count(value => value > 1e-8f);
                var sum = values.Sum();
                if (positive == 0)
                    report.metrics.unweightedVertices++;
                else if (Mathf.Abs(sum - 1f) > 1e-4f)
                    report.metrics.weightSumErrors++;
            }

            if (mesh.bindposes.Length != rendererBones.Length)
                report.warnings.Add($"bindpose/bone count differs: {mesh.name}");
        }

        private static void CreatePrefab(GameObject model, string prefabPath, Report report)
        {
            EnsureAssetFolder(Path.GetDirectoryName(prefabPath)?.Replace('\\', '/'));
            var instance = PrefabUtility.InstantiatePrefab(model) as GameObject;
            if (instance == null)
            {
                report.errors.Add("could not instantiate FBX");
                return;
            }

            try
            {
                instance.name = Path.GetFileNameWithoutExtension(prefabPath);
                ConfigureOutfitPrefab(instance, report);
                var saved = PrefabUtility.SaveAsPrefabAsset(instance, prefabPath);
                if (saved == null)
                    report.errors.Add("could not save prefab");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        private static void ConfigureOutfitPrefab(GameObject outfitRoot, Report report)
        {
            var renderer = outfitRoot.GetComponentsInChildren<SkinnedMeshRenderer>(true).FirstOrDefault();
            if (renderer == null || renderer.rootBone == null)
            {
                report.errors.Add("outfit root bone not found");
                return;
            }

            var armature = renderer.rootBone;
            while (armature.parent != null && armature.parent != outfitRoot.transform)
                armature = armature.parent;

            var merge = armature.GetComponent<ModularAvatarMergeArmature>();
            if (merge == null)
                merge = armature.gameObject.AddComponent<ModularAvatarMergeArmature>();
            merge.mergeTarget = new AvatarObjectReference
            {
                referencePath = armature.name
            };
            merge.LockMode = ArmatureLockMode.BaseToMerge;
            merge.mangleNames = false;

            var settings = outfitRoot.GetComponent<ModularAvatarMeshSettings>();
            if (settings == null)
                settings = outfitRoot.AddComponent<ModularAvatarMeshSettings>();
            settings.InheritProbeAnchor = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
            settings.InheritBounds = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
            settings.ProbeAnchor = new AvatarObjectReference
            {
                referencePath = $"{armature.name}/{renderer.rootBone.name}"
            };
            settings.RootBone = new AvatarObjectReference
            {
                referencePath = $"{armature.name}/{renderer.rootBone.name}"
            };
            settings.Bounds = renderer.localBounds;
        }

        private static void CreateIntegratedPrefab(Job job, Report report)
        {
            var target = AssetDatabase.LoadAssetAtPath<GameObject>(job.targetAvatarAssetPath);
            var outfit = AssetDatabase.LoadAssetAtPath<GameObject>(job.prefabAssetPath);
            var targetInstance = PrefabUtility.InstantiatePrefab(target) as GameObject;
            var outfitInstance = PrefabUtility.InstantiatePrefab(outfit) as GameObject;
            outfitInstance.transform.SetParent(targetInstance.transform, false);
            outfitInstance.name = Path.GetFileNameWithoutExtension(job.prefabAssetPath);
            ConfigureOutfitPrefab(outfitInstance, report);
            EnsureAssetFolder(Path.GetDirectoryName(job.integratedPrefabAssetPath)?.Replace('\\', '/'));
            var saved = PrefabUtility.SaveAsPrefabAsset(targetInstance, job.integratedPrefabAssetPath);
            if (saved == null)
                report.errors.Add("could not save integrated avatar prefab");
            UnityEngine.Object.DestroyImmediate(targetInstance);
        }

        private static async Task<BuildTestReport> RunBuildAndTest(Job job)
        {
            var report = new BuildTestReport
            {
                status = "FAIL",
                checkedAt = DateTime.UtcNow.ToString("O"),
                unityVersion = Application.unityVersion,
                combinedPrefabAssetPath = job.integratedPrefabAssetPath
            };
            if (VRCSdkControlPanel.window == null)
                VRCSdkControlPanel.window = ScriptableObject.CreateInstance<VRCSdkControlPanel>();
            if (!VRCSdkControlPanel.TryGetBuilder<IVRCSdkAvatarBuilderApi>(out var builder))
            {
                report.error = "VRChat SDK avatar builder unavailable";
                return report;
            }

            var avatar = PrefabUtility.LoadPrefabContents(job.integratedPrefabAssetPath);
            builder.SelectAvatar(avatar);
            report.builderType = builder.GetType().FullName;
            var buildTask = builder.BuildAndTest(avatar);
            var completedTask = await Task.WhenAny(buildTask, Task.Delay(TimeSpan.FromSeconds(60)));
            if (completedTask != buildTask)
            {
                report.buildState = builder.BuildState.ToString();
                report.error = "VRChat SDK Build & Test timed out while waiting for the local VRChat client";
                PrefabUtility.UnloadPrefabContents(avatar);
                return report;
            }
            await buildTask;
            report.buildState = builder.BuildState.ToString();
            report.passed = builder.BuildState == SdkBuildState.Success;
            report.status = report.passed ? "PASS" : "FAIL";
            if (!report.passed)
                report.error = "VRChat SDK Build & Test did not finish successfully";
            PrefabUtility.UnloadPrefabContents(avatar);
            return report;
        }

        private static void ValidateTarget(GameObject outfitModel, Job job, Report report)
        {
            var target = AssetDatabase.LoadAssetAtPath<GameObject>(job.targetAvatarAssetPath);
            if (target == null)
            {
                report.errors.Add("exact target avatar prefab not found");
                return;
            }

            var animator = target.GetComponentInChildren<Animator>(true);
            if (animator == null || animator.avatar == null || !animator.avatar.isHuman)
            {
                report.errors.Add("target avatar is not a valid Humanoid");
                return;
            }

            var requiredHumanBones = new[]
            {
                HumanBodyBones.Head,
                HumanBodyBones.LeftHand,
                HumanBodyBones.RightHand,
                HumanBodyBones.LeftFoot,
                HumanBodyBones.RightFoot
            };
            foreach (var bone in requiredHumanBones)
            {
                if (animator.GetBoneTransform(bone) == null)
                    report.errors.Add($"target Humanoid bone missing: {bone}");
            }

            var targetBoneNames = new HashSet<string>(
                target.GetComponentsInChildren<Transform>(true).Select(transform => transform.name),
                StringComparer.Ordinal);
            var allowed = new HashSet<string>(
                job.allowedExtraBones ?? Array.Empty<string>(),
                StringComparer.Ordinal);

            foreach (var renderer in outfitModel.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                foreach (var bone in renderer.bones.Where(bone => bone != null))
                {
                    if (!targetBoneNames.Contains(bone.name) && !allowed.Contains(bone.name))
                        report.errors.Add($"outfit bone not found on target: {bone.name}");
                }
            }

            var descriptorType = FindType("VRC.SDK3.Avatars.Components.VRCAvatarDescriptor");
            if (descriptorType == null || target.GetComponentInChildren(descriptorType, true) == null)
                report.errors.Add("VRCAvatarDescriptor missing on target");

            report.targetValidated = !report.errors.Any();
        }

        private static Type FindType(string fullName)
        {
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                var type = assembly.GetType(fullName, false);
                if (type != null)
                    return type;
            }
            return null;
        }

        private static void WriteReport(Job job, Report report)
        {
            var projectRoot = Path.GetDirectoryName(Application.dataPath);
            var reportDirectory = Path.GetFullPath(Path.Combine(projectRoot, job.artifactDir));
            Directory.CreateDirectory(reportDirectory);
            File.WriteAllText(
                Path.Combine(reportDirectory, "unity.json"),
                JsonUtility.ToJson(report, true));
        }

        private static void WriteBuildTestReport(Job job, BuildTestReport report)
        {
            var projectRoot = Path.GetDirectoryName(Application.dataPath);
            var reportDirectory = Path.GetFullPath(Path.Combine(projectRoot, job.artifactDir));
            Directory.CreateDirectory(reportDirectory);
            File.WriteAllText(
                Path.Combine(reportDirectory, "vrchat-build-test.json"),
                JsonUtility.ToJson(report, true));
        }

        private static void RequireAssetPath(string value, string name)
        {
            if (string.IsNullOrWhiteSpace(value) || !value.StartsWith("Assets/", StringComparison.Ordinal))
                throw new ArgumentException($"{name} must be an Assets/ path");
        }

        private static void EnsureAssetFolder(string folder)
        {
            if (string.IsNullOrWhiteSpace(folder) || folder == "Assets" || AssetDatabase.IsValidFolder(folder))
                return;

            var parent = Path.GetDirectoryName(folder)?.Replace('\\', '/');
            EnsureAssetFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(folder));
        }

        private static string GetArgument(string name)
        {
            var args = Environment.GetCommandLineArgs();
            for (var index = 0; index + 1 < args.Length; index++)
            {
                if (args[index] == name)
                    return args[index + 1];
            }
            return null;
        }

        private static bool Finite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static string GetPath(Transform transform)
        {
            var names = new List<string>();
            while (transform != null)
            {
                names.Add(transform.name);
                transform = transform.parent;
            }
            names.Reverse();
            return string.Join("/", names);
        }
    }
}
#endif

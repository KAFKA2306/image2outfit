#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using nadena.dev.modular_avatar.core;
using nadena.dev.ndmf;
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
            public bool toolchainValidated;
            public bool modularAvatarValidated;
            public bool buildAndTestPassed;
            public string unityVersion;
            public string modularAvatarVersion;
            public string ndmfVersion;
            public string avatarOptimizerVersion;
            public string vrchatAvatarsVersion;
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
            RunInternal(true);
        }

        public static void RunStatic()
        {
            RunInternal(false);
        }

        private static void RunInternal(bool runBuildAndTest)
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
                if (report.passed && runBuildAndTest)
                {
                    EditorApplication.delayCall += () => FinishRun(job, report);
                    return;
                }

                if (report.passed)
                {
                    var buildTest = new BuildTestReport
                    {
                        status = "SKIPPED",
                        checkedAt = DateTime.UtcNow.ToString("O"),
                        passed = false,
                        unityVersion = Application.unityVersion,
                        combinedPrefabAssetPath = job.integratedPrefabAssetPath,
                        error = "VRChat client test is performed by a human outside the repository"
                    };
                    report.buildAndTestPassed = false;
                    WriteBuildTestReport(job, buildTest);
                    WriteReport(job, report);
                    EditorApplication.Exit(0);
                    return;
                }

                var failedBuildTest = new BuildTestReport
                {
                    status = "FAIL",
                    checkedAt = DateTime.UtcNow.ToString("O"),
                    passed = false,
                    unityVersion = Application.unityVersion,
                    combinedPrefabAssetPath = job.integratedPrefabAssetPath,
                    error = "static integration gate failed"
                };
                report.buildAndTestPassed = false;
                WriteBuildTestReport(job, failedBuildTest);
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
            ValidateToolchain(report);
            if (report.errors.Any())
                return report;

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
                    && report.toolchainValidated
                    && report.modularAvatarValidated
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

        private static void ValidateToolchain(Report report)
        {
            report.modularAvatarVersion = InstalledPackageVersion("nadena.dev.modular-avatar");
            report.ndmfVersion = InstalledPackageVersion("nadena.dev.ndmf");
            report.avatarOptimizerVersion = InstalledPackageVersion("com.anatawa12.avatar-optimizer");
            report.vrchatAvatarsVersion = InstalledPackageVersion("com.vrchat.avatars");

            if (Application.unityVersion != "2022.3.22f1")
                report.errors.Add($"Unity version mismatch: expected 2022.3.22f1, found {Application.unityVersion}");

            var expectedPackages = new Dictionary<string, string>
            {
                { "nadena.dev.modular-avatar", "1.17.1" },
                { "nadena.dev.ndmf", "1.14.1" },
                { "com.anatawa12.avatar-optimizer", "1.9.16" },
                { "com.vrchat.avatars", "3.10.4" }
            };
            foreach (var package in expectedPackages)
            {
                var actual = InstalledPackageVersion(package.Key);
                if (actual != package.Value)
                    report.errors.Add($"package version mismatch: {package.Key} expected {package.Value}, found {actual ?? "missing"}");
            }

            report.toolchainValidated = !report.errors.Any();
        }

        private static string InstalledPackageVersion(string packageName)
        {
            return UnityEditor.PackageManager.PackageInfo.GetAllRegisteredPackages()
                .FirstOrDefault(package => package.name == packageName)?.version;
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
            {
                var baseArmatureName = armature.name;
                armature.name = baseArmatureName + ".1";
                merge = armature.gameObject.AddComponent<ModularAvatarMergeArmature>();
                merge.mergeTarget = new AvatarObjectReference
                {
                    referencePath = baseArmatureName
                };
            }
            var targetArmatureName = merge.mergeTarget?.referencePath;
            if (string.IsNullOrWhiteSpace(targetArmatureName))
            {
                report.errors.Add("Merge Armature target path is empty");
                return;
            }
            merge.mergeTarget = new AvatarObjectReference
            {
                referencePath = targetArmatureName
            };
            merge.LockMode = ArmatureLockMode.BaseToMerge;
            merge.mangleNames = true;

            var settings = outfitRoot.GetComponent<ModularAvatarMeshSettings>();
            if (settings == null)
                settings = outfitRoot.AddComponent<ModularAvatarMeshSettings>();
            settings.InheritProbeAnchor = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
            settings.InheritBounds = ModularAvatarMeshSettings.InheritMode.SetOrInherit;
            settings.ProbeAnchor = new AvatarObjectReference
            {
                referencePath = $"{targetArmatureName}/{renderer.rootBone.name}"
            };
            settings.RootBone = new AvatarObjectReference
            {
                referencePath = $"{targetArmatureName}/{renderer.rootBone.name}"
            };
            settings.Bounds = renderer.localBounds;
        }

        private static void CreateIntegratedPrefab(Job job, Report report)
        {
            var target = AssetDatabase.LoadAssetAtPath<GameObject>(job.targetAvatarAssetPath);
            var outfit = AssetDatabase.LoadAssetAtPath<GameObject>(job.prefabAssetPath);
            if (target == null || outfit == null)
            {
                report.errors.Add("target or outfit prefab could not be loaded for integration");
                return;
            }

            GameObject targetInstance = null;
            GameObject outfitInstance = null;
            try
            {
                targetInstance = PrefabUtility.InstantiatePrefab(target) as GameObject;
                outfitInstance = PrefabUtility.InstantiatePrefab(outfit) as GameObject;
                if (targetInstance == null || outfitInstance == null)
                {
                    report.errors.Add("target or outfit prefab could not be instantiated");
                    return;
                }

                outfitInstance.transform.SetParent(targetInstance.transform, false);
                var outfitName = Path.GetFileNameWithoutExtension(job.prefabAssetPath);
                outfitInstance.name = outfitName;
                ConfigureOutfitPrefab(outfitInstance, report);
                if (report.errors.Any())
                    return;

                EnsureAssetFolder(Path.GetDirectoryName(job.integratedPrefabAssetPath)?.Replace('\\', '/'));
                var saved = PrefabUtility.SaveAsPrefabAsset(targetInstance, job.integratedPrefabAssetPath);
                if (saved == null)
                {
                    report.errors.Add("could not save integrated avatar prefab");
                    return;
                }
                ValidateModularAvatarBake(saved, outfitName, report);
            }
            finally
            {
                if (targetInstance != null)
                    UnityEngine.Object.DestroyImmediate(targetInstance);
                else if (outfitInstance != null)
                    UnityEngine.Object.DestroyImmediate(outfitInstance);
            }
        }

        private static void ValidateModularAvatarBake(GameObject integratedPrefab, string outfitName, Report report)
        {
            var instance = PrefabUtility.InstantiatePrefab(integratedPrefab) as GameObject;
            if (instance == null)
            {
                report.errors.Add("integrated prefab could not be instantiated for NDMF validation");
                return;
            }

            var startingErrors = report.errors.Count;
            var temporaryAssetsCleaned = false;
            try
            {
                var outfit = instance.transform.Cast<Transform>()
                    .FirstOrDefault(child => child.name == outfitName);
                if (outfit == null)
                {
                    report.errors.Add("integrated outfit root not found for NDMF validation");
                    return;
                }

                var merges = outfit.GetComponentsInChildren<ModularAvatarMergeArmature>(true);
                if (merges.Length != 1)
                {
                    report.errors.Add($"expected exactly one outfit Merge Armature, found {merges.Length}");
                    return;
                }

                var merge = merges[0];
                var mapping = merge.GetBonesMapping();
                if (mapping == null || mapping.Count == 0)
                    report.errors.Add("Merge Armature did not resolve any target bone mappings");
                if (merge.LockMode != ArmatureLockMode.BaseToMerge)
                    report.errors.Add("Merge Armature must use BaseToMerge position lock");
                if (!merge.mangleNames)
                    report.errors.Add("Merge Armature must avoid unique-bone name collisions");
                if (outfit.GetComponent<ModularAvatarMeshSettings>() == null)
                    report.errors.Add("outfit Mesh Settings component is missing");
                if (!AvatarProcessor.CanProcessObject(instance))
                    report.errors.Add("NDMF cannot process the integrated avatar");
                if (report.errors.Count != startingErrors)
                    return;

                var beforeRenderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length;
                var beforeInvalid = InvalidSkinnedRenderers(instance);
                var beforeMissingScripts = MissingScriptCount(instance);
                AvatarProcessor.ProcessAvatar(instance);
                var afterRenderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length;
                var afterInvalid = InvalidSkinnedRenderers(instance);
                var afterMissingScripts = MissingScriptCount(instance);
                if (afterRenderers < beforeRenderers)
                    report.errors.Add($"NDMF removed skinned renderers: before {beforeRenderers}, after {afterRenderers}");
                if (afterInvalid > beforeInvalid)
                    report.errors.Add($"NDMF introduced invalid skinned renderers: before {beforeInvalid}, after {afterInvalid}");
                if (afterMissingScripts > beforeMissingScripts)
                    report.errors.Add($"NDMF introduced missing scripts: before {beforeMissingScripts}, after {afterMissingScripts}");
            }
            catch (Exception exception)
            {
                report.errors.Add($"NDMF processing failed: {exception.GetType().Name}: {exception.Message}");
            }
            finally
            {
                try
                {
                    AvatarProcessor.CleanTemporaryAssets();
                    temporaryAssetsCleaned = true;
                }
                catch (Exception exception)
                {
                    report.errors.Add($"NDMF temporary asset cleanup failed: {exception.Message}");
                }
                UnityEngine.Object.DestroyImmediate(instance);
            }

            report.modularAvatarValidated = temporaryAssetsCleaned && report.errors.Count == startingErrors;
        }

        private static int InvalidSkinnedRenderers(GameObject root)
        {
            return root.GetComponentsInChildren<SkinnedMeshRenderer>(true).Count(renderer =>
                renderer.sharedMesh == null
                || renderer.rootBone == null
                || renderer.bones.Any(bone => bone == null));
        }

        private static int MissingScriptCount(GameObject root)
        {
            return root.GetComponentsInChildren<Transform>(true)
                .Sum(transform => GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(transform.gameObject));
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

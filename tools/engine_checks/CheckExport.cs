using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

// tools/check_engine_exports.py: checks the Modular Sprite Editor's Unity export (Assets/Pop) against
// Assets/Pop/expected.json, what the editor's exporter says each clip shows. Exits with 1 on a failure.
public static class CheckExport
{
    static int failures;
    static void Fail(string message) { failures++; if (failures <= 25) Debug.Log("FAIL " + message); }

    public static void Run()
    {
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
        var json = File.ReadAllText("Assets/Pop/expected.json");
        var expected = (Dictionary<string, object>)MiniJson.Parse(json);
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Pop/pop.prefab");
        if (prefab == null) { Fail("no prefab"); Finish(); return; }
        var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        var renderer = go.GetComponent<SpriteRenderer>();
        var clips = AssetDatabase.FindAssets("t:AnimationClip", new[] { "Assets/Pop" })
            .Select(g => AssetDatabase.LoadAssetAtPath<AnimationClip>(AssetDatabase.GUIDToAssetPath(g))).ToDictionary(c => c.name);
        var cells = (List<object>)expected["cells"];
        var boxSlots = ((List<object>)expected["boxes"]).Cast<string>().ToList();
        var pointSlots = ((List<object>)expected["points"]).Cast<string>().ToList();
        int samples = 0;
        foreach (Dictionary<string, object> clip in (List<object>)expected["clips"])
        {
            string name = (string)clip["name"];
            if (!clips.TryGetValue(name, out var anim)) { Fail("missing clip " + name); continue; }
            if (Math.Abs(anim.length - Convert.ToSingle(clip["length"])) > 1e-4f) Fail($"{name} length {anim.length}, want {clip["length"]}");
            if (AnimationUtility.GetAnimationClipSettings(anim).loopTime != (bool)clip["loops"]) Fail($"{name} loop");
            var wantEvents = new List<string>();
            foreach (Dictionary<string, object> key in (List<object>)clip["keys"])
            {
                anim.SampleAnimation(go, Convert.ToSingle(key["t"]));
                samples++;
                AssetDatabase.TryGetGUIDAndLocalFileIdentifier(renderer.sprite, out string guid, out long id);
                if (renderer.sprite == null || id.ToString() != (string)key["sprite_id"]) Fail($"{name} at {key["t"]}: sprite {id}, want {key["sprite_id"]}");
                var cell = (Dictionary<string, object>)cells[Convert.ToInt32(key["cell"])];
                if (renderer.sprite != null && (renderer.sprite.pivot - new Vector2(-Convert.ToSingle(cell["left"]), Convert.ToSingle(cell["top"]) + Convert.ToSingle(cell["h"]))).magnitude > 0.01f)
                    Fail($"{name}: pivot {renderer.sprite.pivot}");
                var boxes = (Dictionary<string, object>)key["boxes"];
                foreach (var slot in boxSlots)
                {
                    var collider = go.transform.Find("Hitboxes/" + slot).GetComponent<BoxCollider2D>();
                    if (!boxes.TryGetValue(slot, out var raw)) { if (collider.enabled) Fail($"{name} at {key["t"]}: {slot} should be off"); continue; }
                    var b = ((List<object>)raw).Select(Convert.ToSingle).ToArray();
                    var offset = new Vector2(b[0] / 100f, -b[1] / 100f);
                    var size = new Vector2(b[2] / 100f, b[3] / 100f);
                    if (!collider.enabled || (collider.offset - offset).magnitude > 1e-4f || (collider.size - size).magnitude > 1e-4f)
                        Fail($"{name} at {key["t"]}: {slot} {collider.enabled} {collider.offset} {collider.size}, want {offset} {size}");
                }
                var points = (Dictionary<string, object>)key["points"];
                foreach (var slot in pointSlots)
                {
                    var point = go.transform.Find("Points/" + slot);
                    if (!points.TryGetValue(slot, out var raw)) { if (point.gameObject.activeSelf) Fail($"{name} at {key["t"]}: {slot} should be inactive"); continue; }
                    var p = ((List<object>)raw).Select(Convert.ToSingle).ToArray();
                    var want = new Vector3(p[0] / 100f, -p[1] / 100f, 0f);
                    if (!point.gameObject.activeSelf || (point.localPosition - want).magnitude > 1e-4f)
                        Fail($"{name} at {key["t"]}: {slot} {point.gameObject.activeSelf} {point.localPosition}, want {want}");
                }
                foreach (List<object> e in (List<object>)key["events"])
                    wantEvents.Add($"{Convert.ToSingle(key["start"]):0.###}:{e[0]}:{e[1]}");
            }
            var gotEvents = AnimationUtility.GetAnimationEvents(anim).Select(e => $"{e.time:0.###}:{e.stringParameter}:{e.intParameter}").ToList();
            if (!gotEvents.SequenceEqual(wantEvents)) Fail($"{name} events {string.Join(",", gotEvents)}, want {string.Join(",", wantEvents)}");
            if (AnimationUtility.GetAnimationEvents(anim).Any(e => e.functionName != "OnSpriteEvent")) Fail($"{name} event function");
        }
        // The controller: a state per clip, the first the default, follow-ups as transitions at the end.
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>("Assets/Pop/pop.controller");
        var machine = controller.layers[0].stateMachine;
        var states = machine.states.Select(s => s.state).ToDictionary(s => s.name);
        var expectedClips = ((List<object>)expected["clips"]).Cast<Dictionary<string, object>>().ToList();
        if (machine.defaultState == null || machine.defaultState.name != (string)expectedClips[0]["name"]) Fail("default state");
        foreach (var clip in expectedClips)
        {
            string name = (string)clip["name"];
            if (!states.TryGetValue(name, out var state)) { Fail("no state " + name); continue; }
            if (state.motion == null || state.motion.name != name) Fail($"state {name} plays {state.motion}");
            var next = clip["next"] as string;
            var transitions = state.transitions;
            if (next == null ? transitions.Length != 0 : transitions.Length != 1 || transitions[0].destinationState.name != next || !transitions[0].hasExitTime || transitions[0].exitTime != 1f)
                Fail($"state {name} transitions {string.Join(",", transitions.Select(t => t.destinationState?.name))}, want {next}");
        }
        // The Animator runs a clip into its follow-up.
        var animator = go.GetComponent<Animator>();
        foreach (var clip in expectedClips.Where(c => c["next"] != null))
        {
            animator.Rebind();
            animator.Play((string)clip["name"], 0, 0f);
            animator.Update(0f);
            float length = Convert.ToSingle(clip["length"]);
            for (float t = 0f; t < length + 0.05f; t += 1f / 60f) animator.Update(1f / 60f);
            if (!animator.GetCurrentAnimatorStateInfo(0).IsName((string)clip["next"])) Fail($"{clip["name"]} did not go on with {clip["next"]}");
        }
        // A script with OnSpriteEvent receives the events while the Animator plays.
        go.AddComponent<EventProbe>();
        foreach (var clip in expectedClips)
        {
            var want = ((List<object>)clip["keys"]).Cast<Dictionary<string, object>>()
                .SelectMany(k => ((List<object>)k["events"]).Cast<List<object>>().Select(e => $"{e[0]}:{e[1]}")).ToList();
            if (want.Count == 0) continue;
            EventProbe.Fired.Clear();
            animator.Rebind();
            animator.Play((string)clip["name"], 0, 0f);
            animator.Update(0f);
            float length = Convert.ToSingle(clip["length"]);
            for (float t = 0f; t < length - 0.02f; t += 1f / 120f) animator.Update(1f / 120f);
            if (!EventProbe.Fired.SequenceEqual(want)) Fail($"{clip["name"]} received {string.Join(",", EventProbe.Fired)}, want {string.Join(",", want)}");
            else Debug.Log($"RECEIVED {clip["name"]}: {string.Join(",", EventProbe.Fired)}");
        }
        Debug.Log($"CHECKED clips={clips.Count} samples={samples} failures={failures}");
        UnityEngine.Object.DestroyImmediate(go);
        Finish();
    }

    static void Finish() { EditorApplication.Exit(failures == 0 ? 0 : 1); }
}

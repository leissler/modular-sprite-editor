"""Unity (6): a sprite sheet (``exporters/sheet.py``) as sprites, animation clips, an Animator Controller and a prefab
(wx-free). Written as the text assets the Unity Editor writes itself (checked against what Unity 6 writes and loaded
there), so Unity needs no importer script:

- ``<name>.png.meta``: the texture cut into sprites (point filtering, no compression), each pivot on the editor's
  origin; the meta's layout keeps the sprites' ids, which the clips refer to.
- ``<name> Animations/<clip>.anim``: a clip per clip (``sheet.clips``): the SpriteRenderer's sprite, each hitbox slot's
  BoxCollider2D (on or off, offset and size) and each point slot's position and whether it is there, stepped, at the
  animation's tick rate; step events call ``OnSpriteEvent(AnimationEvent)`` with the event's name as its string and
  its value as its int (on any script of the GameObject that has the method; without one they stay silent).
- ``<name>.controller``: a state per clip (the first one is the default), follow-ups and the loop after an intro as
  transitions at the end of the clip.
- ``<name>.prefab``: the character: SpriteRenderer and Animator on the root (the editor's origin), ``Hitboxes/<slot>``
  with a trigger BoxCollider2D each, ``Points/<slot>`` transforms.

Units: ``PIXELS_PER_UNIT`` sheet pixels a unit, y up. Every file's guid comes from its path, so exporting to the same
place again keeps scenes that use the prefab working.
"""

from __future__ import annotations

import hashlib
import os
import re
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

from exporters import sheet as sheets

PIXELS_PER_UNIT = 100
EVENT_FUNCTION = "OnSpriteEvent"
HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
CLASS_GAMEOBJECT, CLASS_TRANSFORM, CLASS_BOXCOLLIDER2D, CLASS_SPRITERENDERER = 1, 4, 61, 212


def guid(seed: str) -> str:
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def local_id(seed: str) -> int:
    """A file-local object id (positive, never 0)."""
    return int(hashlib.md5(seed.encode("utf-8")).hexdigest()[:15], 16) + 1


def sprite_id(seed: str, index: int) -> int:
    """The id of the sheet's sprite ``index`` (what clips and the prefab refer to)."""
    return int(guid(f"{seed}/{index}")[:15], 16)


def _num(value: float) -> str:
    text = f"{float(value):.9g}"
    return "0" if text == "-0" else text


def _str(text: str) -> str:
    """A YAML scalar: plain when that reads back as the same text, else single-quoted."""
    if text and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9 _.()-]*", text) and not text.endswith(" "):
        return text
    return "'" + text.replace("'", "''") + "'"


def _meta(file_guid: str, importer: str) -> str:
    if importer == "prefab":
        return "\n".join(["fileFormatVersion: 2", f"guid: {file_guid}", "PrefabImporter:", "  externalObjects: {}",
                          "  userData: ", "  assetBundleName: ", "  assetBundleVariant: ", ""])
    main = {"anim": 7400000, "controller": 9100000}[importer]
    return "\n".join(["fileFormatVersion: 2", f"guid: {file_guid}", "NativeFormatImporter:", "  externalObjects: {}",
                      f"  mainObjectFileID: {main}", "  userData: ", "  assetBundleName: ", "  assetBundleVariant: ", ""])


# ---------------------------------------------------------------------------- the texture
def sprite_names(sheet: sheets.Sheet) -> List[str]:
    names: Dict[str, int] = {}
    out = []
    for cell in sheet.cells:
        name = cell.name
        names[name] = names.get(name, 0) + 1
        out.append(name if names[name] == 1 else f"{name}_{names[name]}")
    return out


def texture_meta(sheet: sheets.Sheet, seed: str) -> str:
    """The texture's import settings in Unity 6's layout (serializedVersion 13, with the name → id table, so Unity
    keeps the sprite ids): sprite mode Multiple, point filtering, no compression, every cell a sprite whose pivot is
    the editor's origin (Unity counts y from the bottom)."""
    sheet_h = sheet.image.size[1]
    names = sprite_names(sheet)
    sprites = []
    for index, cell in enumerate(sheet.cells):
        w, h = cell.size
        sprites.append("\n".join([
            "    - serializedVersion: 2",
            f"      name: {_str(names[index])}",
            "      rect:",
            "        serializedVersion: 2",
            f"        x: {cell.x}",
            f"        y: {sheet_h - cell.y - h}",
            f"        width: {w}",
            f"        height: {h}",
            "      alignment: 9",
            f"      pivot: {{x: {_num(-cell.left / float(w))}, y: {_num((cell.top + h) / float(h))}}}",
            "      border: {x: 0, y: 0, z: 0, w: 0}",
            "      customData: ",
            "      outline: []",
            "      physicsShape: []",
            "      tessellationDetail: 0",
            "      bones: []",
            f"      spriteID: {guid(f'{seed}/sprite/{index}')}",
            f"      internalID: {sprite_id(seed, index)}",
            "      vertices: []",
            "      indices: ",
            "      edges: []",
            "      weights: []",
        ]))
    table = [f"      {_str(name)}: {sprite_id(seed, index)}" for index, name in enumerate(names)]
    return "\n".join([
        "fileFormatVersion: 2",
        f"guid: {guid(seed)}",
        "TextureImporter:",
        "  internalIDToNameTable: []",
        "  externalObjects: {}",
        "  serializedVersion: 13",
        "  mipmaps:",
        "    mipMapMode: 0",
        "    enableMipMap: 0",
        "    sRGBTexture: 1",
        "    linearTexture: 0",
        "  isReadable: 0",
        "  textureFormat: 1",
        "  maxTextureSize: 8192",
        "  textureSettings:",
        "    serializedVersion: 2",
        "    filterMode: 0",
        "    aniso: 1",
        "    mipBias: 0",
        "    wrapU: 1",
        "    wrapV: 1",
        "    wrapW: 1",
        "  nPOTScale: 0",
        "  lightmap: 0",
        "  compressionQuality: 50",
        "  spriteMode: 2",
        "  spriteExtrude: 1",
        "  spriteMeshType: 0",
        "  alignment: 9",
        "  spritePivot: {x: 0.5, y: 0.5}",
        f"  spritePixelsToUnits: {PIXELS_PER_UNIT}",
        "  spriteBorder: {x: 0, y: 0, z: 0, w: 0}",
        "  spriteGenerateFallbackPhysicsShape: 1",
        "  alphaUsage: 1",
        "  alphaIsTransparency: 1",
        "  textureType: 8",
        "  textureShape: 1",
        "  platformSettings:",
        "  - serializedVersion: 4",
        "    buildTarget: DefaultTexturePlatform",
        "    maxTextureSize: 8192",
        "    resizeAlgorithm: 0",
        "    textureFormat: -1",
        "    textureCompression: 0",
        "    compressionQuality: 50",
        "    crunchedCompression: 0",
        "    allowsAlphaSplitting: 0",
        "    overridden: 0",
        "  spriteSheet:",
        "    serializedVersion: 2",
        "    sprites:",
        *sprites,
        "    outline: []",
        "    customData: ",
        "    physicsShape: []",
        "    bones: []",
        "    spriteID: ",
        "    internalID: 0",
        "    vertices: []",
        "    indices: ",
        "    edges: []",
        "    weights: []",
        "    secondaryTextures: []",
        "    spriteCustomMetadata:",
        "      entries: []",
        "    nameFileIdTable:",
        *table,
        "  mipmapLimitGroupName: ",
        "  pSDRemoveMatte: 0",
        "  userData: ",
        "  assetBundleName: ",
        "  assetBundleVariant: ",
        "",
    ])


# ---------------------------------------------------------------------------- clips
def _float_keys(keys: Sequence[Tuple[float, float]]) -> List[str]:
    out = []
    for time, value in keys:
        out += ["      - serializedVersion: 3", f"        time: {_num(time)}", f"        value: {_num(value)}",
                "        inSlope: Infinity", "        outSlope: Infinity", "        tangentMode: 103",
                "        weightedMode: 0", "        inWeight: 0", "        outWeight: 0"]
    return out


def _float_curve(keys: Sequence[Tuple[float, float]], attribute: str, path: str, class_id: int) -> List[str]:
    return (["  - serializedVersion: 2", "    curve:", "      serializedVersion: 2", "      m_Curve:"]
            + _float_keys(keys)
            + ["      m_PreInfinity: 2", "      m_PostInfinity: 2", "      m_RotationOrder: 4",
               f"    attribute: {attribute}", f"    path: {_str(path)}", f"    classID: {class_id}",
               "    script: {fileID: 0}", "    flags: 16"])


def _position_curve(keys: Sequence[Tuple[float, Tuple[float, float]]], path: str) -> List[str]:
    out = ["  - curve:", "      serializedVersion: 2", "      m_Curve:"]
    for time, (x, y) in keys:
        out += ["      - serializedVersion: 3", f"        time: {_num(time)}",
                f"        value: {{x: {_num(x)}, y: {_num(y)}, z: 0}}",
                "        inSlope: {x: Infinity, y: Infinity, z: 0}", "        outSlope: {x: Infinity, y: Infinity, z: 0}",
                "        tangentMode: 0", "        weightedMode: 0",
                "        inWeight: {x: 0, y: 0, z: 0.33333334}", "        outWeight: {x: 0, y: 0, z: 0.33333334}"]
    return out + ["      m_PreInfinity: 2", "      m_PostInfinity: 2", "      m_RotationOrder: 4", f"    path: {_str(path)}"]


def _binding(path: str, attribute: int, type_id: int, pptr: bool = False) -> List[str]:
    return ["    - serializedVersion: 2", f"      path: {zlib.crc32(path.encode('utf-8'))}", f"      attribute: {attribute}",
            "      script: {fileID: 0}", f"      typeID: {type_id}", f"      customType: {23 if pptr else 0}",
            f"      isPPtrCurve: {1 if pptr else 0}", "      isIntCurve: 0", "      isSerializeReferenceCurve: 0",
            "      metaData: 0"]


def _stepped(starts: Sequence[float], values: Sequence[object]) -> List[Tuple[float, object]]:
    """The first key, then one wherever the value changes (the curves are stepped)."""
    out: List[Tuple[float, object]] = []
    for time, value in zip(starts, values):
        if not out or out[-1][1] != value:
            out.append((time, value))
    return out


def _carried(values: List[Optional[tuple]], fallback: tuple) -> List[tuple]:
    known = next((v for v in values if v is not None), fallback)
    out = []
    for value in values:
        known = value if value is not None else known
        out.append(known)
    return out


def clip_yaml(sheet: sheets.Sheet, clip: sheets.Clip, seed: str, box_slots: Sequence[str],
              point_slots: Sequence[str]) -> str:
    tag = sheet.tags[clip.tag]
    times = clip.times(sheet)
    starts, length = times[:-1], times[-1]
    entries = [sheet.entries[i] for i in clip.entries]
    unit = float(PIXELS_PER_UNIT)
    texture = guid(seed)

    positions: List[str] = []
    floats: List[Tuple[List[Tuple[float, float]], str, str, int]] = []  # (keys, attribute, path, class)
    editor: List[Tuple[List[Tuple[float, float]], str, str, int]] = []
    bindings: List[str] = []
    for slot in point_slots:
        path = f"Points/{slot}"
        found = [dict(zip(sheets.slot_names(e.points), e.points)).get(slot) for e in entries]
        places = _carried([((p.x + p.size / 2.0) / unit, -(p.y + p.size / 2.0) / unit) if p else None for p in found],
                          (0.0, 0.0))
        keys = _stepped(starts, places)
        positions += _position_curve(keys, path)  # type: ignore[arg-type]
        bindings += _binding(path, 1, CLASS_TRANSFORM)
        editor += [([(t, v[0]) for t, v in keys], "m_LocalPosition.x", path, CLASS_TRANSFORM),  # type: ignore[index]
                   ([(t, v[1]) for t, v in keys], "m_LocalPosition.y", path, CLASS_TRANSFORM),  # type: ignore[index]
                   ([(keys[0][0], 0.0)], "m_LocalPosition.z", path, CLASS_TRANSFORM)]
        floats.append((_stepped(starts, [1.0 if p else 0.0 for p in found]), "m_IsActive", path, CLASS_GAMEOBJECT))
    for slot in box_slots:
        path = f"Hitboxes/{slot}"
        found = [dict(zip(sheets.slot_names(e.boxes), e.boxes)).get(slot) for e in entries]
        offsets = _carried([((b.x + b.w / 2.0) / unit, -(b.y + b.h / 2.0) / unit) if b else None for b in found],
                           (0.0, 0.0))
        sizes = _carried([(b.w / unit, b.h / unit) if b else None for b in found], (0.01, 0.01))
        floats += [(_stepped(starts, [1.0 if b else 0.0 for b in found]), "m_Enabled", path, CLASS_BOXCOLLIDER2D),
                   (_stepped(starts, [v[0] for v in offsets]), "m_Offset.x", path, CLASS_BOXCOLLIDER2D),
                   (_stepped(starts, [v[1] for v in offsets]), "m_Offset.y", path, CLASS_BOXCOLLIDER2D),
                   (_stepped(starts, [v[0] for v in sizes]), "m_Size.x", path, CLASS_BOXCOLLIDER2D),
                   (_stepped(starts, [v[1] for v in sizes]), "m_Size.y", path, CLASS_BOXCOLLIDER2D)]
    for keys, attribute, path, class_id in floats:
        bindings += _binding(path, zlib.crc32(attribute.encode("utf-8")), class_id)
    editor += floats

    # The sprite: a key at each step, and one a tick before the end (Unity adds a sample to a sprite curve's last key).
    sprite_keys = [(t, e.cell) for t, e in zip(starts, entries)]
    last = length - 1.0 / tag.fps
    if last > sprite_keys[-1][0] + 1e-9:
        sprite_keys.append((last, entries[-1].cell))
    bindings += _binding("", 0, CLASS_SPRITERENDERER, pptr=True)

    def sprite_ref(cell: int) -> str:
        return f"{{fileID: {sprite_id(seed, cell)}, guid: {texture}, type: 3}}"

    lines = [HEADER + "--- !u!74 &7400000", "AnimationClip:", "  m_ObjectHideFlags: 0",
             "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}", "  m_PrefabAsset: {fileID: 0}",
             f"  m_Name: {_str(clip.name)}", "  serializedVersion: 8", "  m_Legacy: 0", "  m_Compressed: 0",
             "  m_UseHighQualityCurve: 1", "  m_RotationCurves: []", "  m_CompressedRotationCurves: []",
             "  m_EulerCurves: []"]
    lines += ["  m_PositionCurves:"] + positions if positions else ["  m_PositionCurves: []"]
    lines.append("  m_ScaleCurves: []")
    float_lines = [line for keys, attribute, path, class_id in floats for line in _float_curve(keys, attribute, path, class_id)]
    lines += ["  m_FloatCurves:"] + float_lines if float_lines else ["  m_FloatCurves: []"]
    lines += ["  m_PPtrCurves:", "  - serializedVersion: 2", "    curve:"]
    for time, cell in sprite_keys:
        lines += [f"    - time: {_num(time)}", f"      value: {sprite_ref(cell)}"]
    lines += ["    attribute: m_Sprite", "    path: ", f"    classID: {CLASS_SPRITERENDERER}", "    script: {fileID: 0}",
              "    flags: 2", f"  m_SampleRate: {tag.fps}", "  m_WrapMode: 0", "  m_Bounds:",
              "    m_Center: {x: 0, y: 0, z: 0}", "    m_Extent: {x: 0, y: 0, z: 0}", "  m_ClipBindingConstant:",
              "    genericBindings:"] + bindings + ["    pptrCurveMapping:"]
    lines += [f"    - {sprite_ref(cell)}" for _time, cell in sprite_keys]
    lines += ["  m_AnimationClipSettings:", "    serializedVersion: 2", "    m_AdditiveReferencePoseClip: {fileID: 0}",
              "    m_AdditiveReferencePoseTime: 0", "    m_StartTime: 0", f"    m_StopTime: {_num(length)}",
              "    m_OrientationOffsetY: 0", "    m_Level: 0", "    m_CycleOffset: 0", "    m_HasAdditiveReferencePose: 0",
              f"    m_LoopTime: {1 if clip.loops else 0}", "    m_LoopBlend: 0", "    m_LoopBlendOrientation: 0",
              "    m_LoopBlendPositionY: 0", "    m_LoopBlendPositionXZ: 0", "    m_KeepOriginalOrientation: 0",
              "    m_KeepOriginalPositionY: 1", "    m_KeepOriginalPositionXZ: 0", "    m_HeightFromFeet: 0",
              "    m_Mirror: 0"]
    editor_lines = [line for keys, attribute, path, class_id in editor for line in _float_curve(keys, attribute, path, class_id)]
    lines += ["  m_EditorCurves:"] + editor_lines if editor_lines else ["  m_EditorCurves: []"]
    lines += ["  m_EulerEditorCurves: []", "  m_HasGenericRootTransform: 0", "  m_HasMotionFloatCurves: 0"]
    events = [(t, name, value) for t, e in zip(starts, entries) for name, value in e.events]
    if events:
        lines.append("  m_Events:")
        for time, name, value in events:
            lines += [f"  - time: {_num(time)}", f"    functionName: {EVENT_FUNCTION}", f"    data: {_str(name)}",
                      "    objectReferenceParameter: {fileID: 0}", "    floatParameter: 0", f"    intParameter: {value}",
                      "    messageOptions: 1"]  # DontRequireReceiver: silent until a script implements it
    else:
        lines.append("  m_Events: []")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- the Animator Controller
def controller_yaml(name: str, clips: Sequence[sheets.Clip], clip_guids: Dict[str, str]) -> str:
    machine = local_id(f"{name}/machine")
    state = {clip.name: local_id(f"{name}/state/{clip.name}") for clip in clips}
    parts = [HEADER + "--- !u!91 &9100000", "AnimatorController:", "  m_ObjectHideFlags: 0",
             "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}", "  m_PrefabAsset: {fileID: 0}",
             f"  m_Name: {_str(name)}", "  serializedVersion: 6", "  m_AnimatorParameters: []", "  m_AnimatorLayers:",
             "  - serializedVersion: 5", "    m_Name: Base Layer", f"    m_StateMachine: {{fileID: {machine}}}",
             "    m_Mask: {fileID: 0}", "    m_Motions: []", "    m_Behaviours: []", "    m_BlendingMode: 0",
             "    m_SyncedLayerIndex: -1", "    m_DefaultWeight: 0", "    m_IKPass: 0", "    m_SyncedLayerAffectsTiming: 0",
             "    m_Controller: {fileID: 9100000}", "  m_EvaluateTransitionsOnStart: 1",
             f"--- !u!1107 &{machine}", "AnimatorStateMachine:", "  serializedVersion: 7", "  m_ObjectHideFlags: 1",
             "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}", "  m_PrefabAsset: {fileID: 0}",
             "  m_Name: Base Layer", "  m_ChildStates:" if clips else "  m_ChildStates: []"]
    for index, clip in enumerate(clips):
        parts += ["  - serializedVersion: 1", f"    m_State: {{fileID: {state[clip.name]}}}",
                  f"    m_Position: {{x: {300 + (index % 4) * 240}, y: {(index // 4) * 70}, z: 0}}"]
    parts += ["  m_ChildStateMachines: []", "  m_AnyStateTransitions: []", "  m_EntryTransitions: []",
              "  m_StateMachineTransitions: {}", "  m_StateMachineBehaviours: []", "  m_AnyStatePosition: {x: 50, y: 20, z: 0}",
              "  m_EntryPosition: {x: 50, y: 120, z: 0}", "  m_ExitPosition: {x: 50, y: 220, z: 0}",
              "  m_ParentStateMachinePosition: {x: 50, y: 320, z: 0}",
              f"  m_DefaultState: {{fileID: {state[clips[0].name] if clips else 0}}}"]
    for clip in clips:
        transition = local_id(f"{name}/transition/{clip.name}") if clip.next in state else None
        parts += [f"--- !u!1102 &{state[clip.name]}", "AnimatorState:", "  serializedVersion: 6", "  m_ObjectHideFlags: 1",
                  "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}",
                  "  m_PrefabAsset: {fileID: 0}", f"  m_Name: {_str(clip.name)}", "  m_Speed: 1", "  m_CycleOffset: 0"]
        parts += ["  m_Transitions:", f"  - {{fileID: {transition}}}"] if transition else ["  m_Transitions: []"]
        parts += ["  m_StateMachineBehaviours: []", "  m_Position: {x: 50, y: 50, z: 0}", "  m_IKOnFeet: 0",
                  "  m_WriteDefaultValues: 1", "  m_Mirror: 0", "  m_SpeedParameterActive: 0", "  m_MirrorParameterActive: 0",
                  "  m_CycleOffsetParameterActive: 0", "  m_TimeParameterActive: 0",
                  f"  m_Motion: {{fileID: 7400000, guid: {clip_guids[clip.name]}, type: 2}}", "  m_Tag: ",
                  "  m_SpeedParameter: ", "  m_MirrorParameter: ", "  m_CycleOffsetParameter: ", "  m_TimeParameter: "]
        if transition:
            parts += [f"--- !u!1101 &{transition}", "AnimatorStateTransition:", "  m_ObjectHideFlags: 1",
                      "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}",
                      "  m_PrefabAsset: {fileID: 0}", "  m_Name: ", "  m_Conditions: []", "  m_DstStateMachine: {fileID: 0}",
                      f"  m_DstState: {{fileID: {state[clip.next]}}}", "  m_Solo: 0", "  m_Mute: 0", "  m_IsExit: 0",
                      "  serializedVersion: 3", "  m_TransitionDuration: 0", "  m_TransitionOffset: 0", "  m_ExitTime: 1",
                      "  m_HasExitTime: 1", "  m_HasFixedDuration: 1", "  m_InterruptionSource: 0",
                      "  m_OrderedInterruption: 1", "  m_CanTransitionToSelf: 1"]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------- the prefab
def _object_header(class_id: int, kind: str, object_id: int) -> List[str]:
    return [f"--- !u!{class_id} &{object_id}", f"{kind}:", "  m_ObjectHideFlags: 0",
            "  m_CorrespondingSourceObject: {fileID: 0}", "  m_PrefabInstance: {fileID: 0}", "  m_PrefabAsset: {fileID: 0}"]


def _game_object(object_id: int, name: str, components: Sequence[int], active: bool = True) -> List[str]:
    return (_object_header(1, "GameObject", object_id) + ["  serializedVersion: 6", "  m_Component:"]
            + [f"  - component: {{fileID: {c}}}" for c in components]
            + ["  m_Layer: 0", f"  m_Name: {_str(name)}", "  m_TagString: Untagged", "  m_Icon: {fileID: 0}",
               "  m_NavMeshLayer: 0", "  m_StaticEditorFlags: 0", f"  m_IsActive: {1 if active else 0}"])


def _transform(object_id: int, game_object: int, father: int, children: Sequence[int],
               position: Tuple[float, float] = (0.0, 0.0)) -> List[str]:
    return (_object_header(4, "Transform", object_id)
            + [f"  m_GameObject: {{fileID: {game_object}}}", "  serializedVersion: 2",
               "  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}",
               f"  m_LocalPosition: {{x: {_num(position[0])}, y: {_num(position[1])}, z: 0}}",
               "  m_LocalScale: {x: 1, y: 1, z: 1}", "  m_ConstrainProportionsScale: 0"]
            + (["  m_Children:"] + [f"  - {{fileID: {c}}}" for c in children] if children else ["  m_Children: []"])
            + [f"  m_Father: {{fileID: {father}}}", "  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}"])


def prefab_yaml(sheet: sheets.Sheet, name: str, seed: str, controller_guid: str, box_slots: Sequence[str],
                point_slots: Sequence[str]) -> str:
    clips = sheets.clips(sheet)
    first = sheet.entries[clips[0].entries[0]] if clips else (sheet.entries[0] if sheet.entries else None)
    unit = float(PIXELS_PER_UNIT)
    ids = {key: local_id(f"{name}/prefab/{key}") for key in ("root", "root.t", "renderer", "animator", "boxes",
                                                             "boxes.t", "points", "points.t")}
    lines: List[str] = []
    box_children, point_children = [], []
    boxes_now = dict(zip(sheets.slot_names(first.boxes), first.boxes)) if first else {}
    points_now = dict(zip(sheets.slot_names(first.points), first.points)) if first else {}
    for slot in box_slots:
        go, tr, col = (local_id(f"{name}/prefab/box/{slot}/{part}") for part in ("go", "t", "collider"))
        box_children.append(tr)
        box = boxes_now.get(slot)
        offset = ((box.x + box.w / 2.0) / unit, -(box.y + box.h / 2.0) / unit) if box else (0.0, 0.0)
        size = (box.w / unit, box.h / unit) if box else (0.01, 0.01)
        lines += _game_object(go, slot, [tr, col]) + _transform(tr, go, ids["boxes.t"], [])
        lines += (_object_header(61, "BoxCollider2D", col)
                  + [f"  m_GameObject: {{fileID: {go}}}", f"  m_Enabled: {1 if box else 0}", "  serializedVersion: 3",
                     "  m_Density: 1", "  m_Material: {fileID: 0}", "  m_IsTrigger: 1", "  m_UsedByEffector: 0",
                     "  m_CompositeOperation: 0", "  m_CompositeOrder: 0",
                     f"  m_Offset: {{x: {_num(offset[0])}, y: {_num(offset[1])}}}", "  m_AutoTiling: 0",
                     f"  m_Size: {{x: {_num(size[0])}, y: {_num(size[1])}}}", "  m_EdgeRadius: 0"])
    for slot in point_slots:
        go, tr = (local_id(f"{name}/prefab/point/{slot}/{part}") for part in ("go", "t"))
        point_children.append(tr)
        point = points_now.get(slot)
        place = (((point.x + point.size / 2.0) / unit, -(point.y + point.size / 2.0) / unit) if point else (0.0, 0.0))
        lines += _game_object(go, slot, [tr], point is not None) + _transform(tr, go, ids["points.t"], [], place)
    children = []
    if box_slots:
        children.append(ids["boxes.t"])
        lines += _game_object(ids["boxes"], "Hitboxes", [ids["boxes.t"]])
        lines += _transform(ids["boxes.t"], ids["boxes"], ids["root.t"], box_children)
    if point_slots:
        children.append(ids["points.t"])
        lines += _game_object(ids["points"], "Points", [ids["points.t"]])
        lines += _transform(ids["points.t"], ids["points"], ids["root.t"], point_children)
    lines += _game_object(ids["root"], name, [ids["root.t"], ids["renderer"], ids["animator"]])
    lines += _transform(ids["root.t"], ids["root"], 0, children)
    sprite = (f"{{fileID: {sprite_id(seed, first.cell)}, guid: {guid(seed)}, type: 3}}" if first else "{fileID: 0}")
    cell = sheet.cells[first.cell] if first else None
    lines += (_object_header(212, "SpriteRenderer", ids["renderer"])
              + [f"  m_GameObject: {{fileID: {ids['root']}}}", "  m_Enabled: 1", "  m_CastShadows: 0",
                 "  m_ReceiveShadows: 0", "  m_DynamicOccludee: 1", "  m_MotionVectors: 1", "  m_LightProbeUsage: 1",
                 "  m_ReflectionProbeUsage: 1", "  m_RenderingLayerMask: 1", "  m_RendererPriority: 0",
                 "  m_Materials:", "  - {fileID: 10754, guid: 0000000000000000f000000000000000, type: 0}",
                 "  m_SortingLayerID: 0", "  m_SortingLayer: 0", "  m_SortingOrder: 0", "  m_MaskInteraction: 0",
                 f"  m_Sprite: {sprite}", "  m_Color: {r: 1, g: 1, b: 1, a: 1}", "  m_FlipX: 0", "  m_FlipY: 0",
                 "  m_DrawMode: 0",
                 f"  m_Size: {{x: {_num(cell.size[0] / unit if cell else 1)}, y: {_num(cell.size[1] / unit if cell else 1)}}}",
                 "  m_AdaptiveModeThreshold: 0.5", "  m_SpriteTileMode: 0", "  m_WasSpriteAssigned: 1",
                 "  m_SpriteSortPoint: 0"])
    lines += (_object_header(95, "Animator", ids["animator"])
              + ["  serializedVersion: 7", f"  m_GameObject: {{fileID: {ids['root']}}}", "  m_Enabled: 1",
                 "  m_Avatar: {fileID: 0}", f"  m_Controller: {{fileID: 9100000, guid: {controller_guid}, type: 2}}",
                 "  m_CullingMode: 0", "  m_UpdateMode: 0", "  m_ApplyRootMotion: 0", "  m_LinearVelocityBlending: 0",
                 "  m_StabilizeFeet: 0", "  m_AnimatePhysics: 0", "  m_WarningMessage: ", "  m_HasTransformHierarchy: 1",
                 "  m_AllowConstantClipSamplingOptimization: 1", "  m_KeepAnimatorStateOnDisable: 0",
                 "  m_WriteDefaultValuesOnDisable: 0"])
    return HEADER + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- everything
def export(sheet: sheets.Sheet, png_path: str, write) -> List[str]:
    """Write the meta, the clips, the controller and the prefab next to the PNG with ``write(path, text)``; returns
    the paths written."""
    png_path = os.path.abspath(png_path)
    folder, stem = os.path.dirname(png_path), os.path.splitext(os.path.basename(png_path))[0]
    seed = png_path
    written = []

    def put(path: str, text: str) -> None:
        write(path, text)
        written.append(path)

    put(png_path + ".meta", texture_meta(sheet, seed))
    clips = sheets.clips(sheet)
    box_slots, point_slots = sheets.slots(sheet, "boxes"), sheets.slots(sheet, "points")
    clip_folder = os.path.join(folder, f"{stem} Animations")
    if clips:
        os.makedirs(clip_folder, exist_ok=True)
    clip_guids = {}
    taken: Dict[str, int] = {}
    for clip in clips:
        path = os.path.join(clip_folder, sheets.unique(sheets.safe_name(clip.name), taken) + ".anim")
        clip_guids[clip.name] = guid(path)
        put(path, clip_yaml(sheet, clip, seed, box_slots, point_slots))
        put(path + ".meta", _meta(clip_guids[clip.name], "anim"))
    controller = os.path.join(folder, f"{stem}.controller")
    put(controller, controller_yaml(stem, clips, clip_guids))
    put(controller + ".meta", _meta(guid(controller), "controller"))
    prefab = os.path.join(folder, f"{stem}.prefab")
    put(prefab, prefab_yaml(sheet, stem, seed, guid(controller), box_slots, point_slots))
    put(prefab + ".meta", _meta(guid(prefab), "prefab"))
    return written

from models import (
    AFrame,
    Animation,
    CollisionRect,
    CollisionType,
    ControlPoint,
    Frame,
    PointType,
    Project,
    generate_id,
)


def test_role_roundtrip_and_legacy_name_migration():
    cp = ControlPoint(id=generate_id("pt"), type_id="ptype", x=4, y=7, role="left_foot")
    cp_loaded = ControlPoint.from_dict(cp.to_dict())
    assert cp_loaded.role == "left_foot"

    cr = CollisionRect(id=generate_id("crect"), type_id="ctype", rect=(1, 2, 3, 4), role="torso_hurt")
    cr_loaded = CollisionRect.from_dict(cr.to_dict())
    assert cr_loaded.role == "torso_hurt"

    legacy_cp = ControlPoint.from_dict({"id": "pt_legacy", "type_id": "ptype", "x": 1, "y": 2, "name": "weapon_tip"})
    assert legacy_cp.role == "weapon_tip"


def test_frame_role_lookup_supports_type_filter():
    ptype_a = PointType(id=generate_id("ptype"), name="socket", color=(0, 255, 0))
    ptype_b = PointType(id=generate_id("ptype"), name="fx", color=(0, 200, 255))
    ctype_a = CollisionType(id=generate_id("ctype"), name="hurtbox", color=(255, 0, 0))
    ctype_b = CollisionType(id=generate_id("ctype"), name="hitbox", color=(255, 200, 0))

    frame = Frame(id=generate_id("frm"), name="pose")
    frame.control_points = [
        ControlPoint(id=generate_id("pt"), type_id=ptype_a.id, x=0, y=0, role="left_foot"),
        ControlPoint(id=generate_id("pt"), type_id=ptype_b.id, x=1, y=1, role="left_foot"),
    ]
    frame.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=ctype_a.id, rect=(0, 0, 2, 2), role="torso_main"),
        CollisionRect(id=generate_id("crect"), type_id=ctype_b.id, rect=(1, 1, 2, 2), role="torso_main"),
    ]

    cp = frame.find_control_point("left_foot")
    assert cp is not None
    assert cp.type_id == ptype_a.id
    assert frame.find_control_point("left_foot", type_id=ptype_b.id).type_id == ptype_b.id
    assert frame.find_control_point("missing") is None

    cr = frame.find_collision_rect("torso_main")
    assert cr is not None
    assert cr.type_id == ctype_a.id
    assert frame.find_collision_rect("torso_main", type_id=ctype_b.id).type_id == ctype_b.id
    assert frame.find_collision_rect("missing") is None


def test_compile_animation_role_tables_uses_minus_one_for_missing_roles():
    project = Project(name="roles")
    ptype = PointType(id=generate_id("ptype"), name="socket", color=(0, 255, 0))
    ctype = CollisionType(id=generate_id("ctype"), name="hurtbox", color=(255, 0, 0))
    project.point_types.append(ptype)
    project.collision_types.append(ctype)

    frame_a = Frame(id=generate_id("frm"), name="A")
    frame_a.control_points = [
        ControlPoint(id=generate_id("pt"), type_id=ptype.id, x=3, y=5, role="left_foot"),
    ]
    frame_a.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=ctype.id, rect=(0, 0, 2, 2), role="torso_main"),
    ]

    frame_b = Frame(id=generate_id("frm"), name="B")
    frame_b.control_points = []
    frame_b.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=ctype.id, rect=(1, 1, 3, 3), role="torso_main"),
    ]

    project.frames = [frame_a, frame_b]

    anim = Animation(id=generate_id("anim"), name="idle", aframes=[
        AFrame(frame_id=frame_a.id, duration_frames=1),
        AFrame(frame_id=frame_b.id, duration_frames=1),
    ])
    project.animations = [anim]

    tables = project.compile_animation_role_tables(anim.id)
    assert tables is not None
    assert tables["frame_ids"] == [frame_a.id, frame_b.id]

    assert tables["point_roles"] == [{"type_id": ptype.id, "role": "left_foot"}]
    assert tables["collision_roles"] == [{"type_id": ctype.id, "role": "torso_main"}]

    # Row values are indices into frame.control_points / frame.collision_rects.
    assert tables["point_table"] == [[0], [-1]]
    assert tables["collision_table"] == [[0], [0]]


def test_validate_role_uniqueness_reports_duplicates_per_frame():
    project = Project(name="validator")
    ptype = PointType(id=generate_id("ptype"), name="socket", color=(0, 255, 0))
    ctype = CollisionType(id=generate_id("ctype"), name="hurtbox", color=(255, 0, 0))
    project.point_types.append(ptype)
    project.collision_types.append(ctype)

    frame = Frame(id=generate_id("frm"), name="Pose")
    frame.control_points = [
        ControlPoint(id=generate_id("pt"), type_id=ptype.id, x=1, y=1, role="Left_Foot"),
        ControlPoint(id=generate_id("pt"), type_id=ptype.id, x=2, y=2, role="left_foot"),
    ]
    frame.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=ctype.id, rect=(0, 0, 2, 2), role="torso_main"),
        CollisionRect(id=generate_id("crect"), type_id=ctype.id, rect=(1, 1, 2, 2), role="TORSO_MAIN"),
    ]
    project.frames = [frame]

    issues = project.validate_role_uniqueness()
    assert len(issues) == 2

    kinds = {issue["kind"] for issue in issues}
    assert kinds == {"point", "collision"}

    for issue in issues:
        assert issue["frame_id"] == frame.id
        assert issue["frame_name"] == frame.name
        assert len(issue["item_ids"]) == 2

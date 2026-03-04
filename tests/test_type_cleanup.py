from models import CollisionRect, CollisionType, ControlPoint, Frame, PointType, Project, generate_id


def test_remove_collision_type_removes_rects_from_all_frames():
    project = Project()
    keep_type = CollisionType(id=generate_id("ctype"), name="Keep", color=(10, 20, 30))
    drop_type = CollisionType(id=generate_id("ctype"), name="Drop", color=(40, 50, 60))
    project.collision_types = [keep_type, drop_type]

    frame_a = Frame(id=generate_id("frm"), name="A")
    frame_a.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=keep_type.id, rect=(0, 0, 1, 1)),
        CollisionRect(id=generate_id("crect"), type_id=drop_type.id, rect=(1, 1, 2, 2)),
    ]
    frame_b = Frame(id=generate_id("frm"), name="B")
    frame_b.collision_rects = [
        CollisionRect(id=generate_id("crect"), type_id=drop_type.id, rect=(2, 2, 3, 3)),
    ]
    project.frames = [frame_a, frame_b]

    removed = project.remove_collision_type(drop_type.id)

    assert removed == 2
    assert [ct.id for ct in project.collision_types] == [keep_type.id]
    assert [cr.type_id for cr in frame_a.collision_rects] == [keep_type.id]
    assert frame_b.collision_rects == []


def test_remove_point_type_removes_points_from_all_frames():
    project = Project()
    keep_type = PointType(id=generate_id("ptype"), name="Keep", color=(10, 20, 30))
    drop_type = PointType(id=generate_id("ptype"), name="Drop", color=(40, 50, 60))
    project.point_types = [keep_type, drop_type]

    frame_a = Frame(id=generate_id("frm"), name="A")
    frame_a.control_points = [
        ControlPoint(id=generate_id("pt"), type_id=keep_type.id, x=0, y=0),
        ControlPoint(id=generate_id("pt"), type_id=drop_type.id, x=1, y=1),
    ]
    frame_b = Frame(id=generate_id("frm"), name="B")
    frame_b.control_points = [
        ControlPoint(id=generate_id("pt"), type_id=drop_type.id, x=2, y=2),
    ]
    project.frames = [frame_a, frame_b]

    removed = project.remove_point_type(drop_type.id)

    assert removed == 2
    assert [pt.id for pt in project.point_types] == [keep_type.id]
    assert [cp.type_id for cp in frame_a.control_points] == [keep_type.id]
    assert frame_b.control_points == []


def test_ensure_default_types_create_expected_defaults():
    project = Project()

    collision_default = project.ensure_default_collision_type()
    point_default = project.ensure_default_point_type()

    assert collision_default.name == "Default"
    assert collision_default.color == (255, 0, 0)
    assert point_default.name == "Default"
    assert point_default.color == (0, 255, 0)
    assert project.collision_types[0].id == collision_default.id
    assert project.point_types[0].id == point_default.id

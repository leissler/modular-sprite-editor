extends SceneTree
## tools/check_engine_exports.py: loads the exported scene (res://pop/pop.tscn) and checks every clip against
## res://pop/expected.json, what the editor's exporter says each clip shows. Exits with 1 on a failure.

var failures := 0


func fail(message: String) -> void:
	failures += 1
	if failures <= 25:
		print("FAIL ", message)


func near(a: Vector2, b: Vector2) -> bool:
	return a.distance_to(b) < 0.01


var node: Node2D
var frames := 0


func _initialize() -> void:
	node = (load("res://pop/pop.tscn") as PackedScene).instantiate()
	root.add_child(node)


func _process(_delta: float) -> bool:
	frames += 1
	if frames < 3:
		return false  # the scene is ready (and autoplay has started) from here on
	check()
	quit(1 if failures else 0)
	return false


func check() -> void:
	var expected: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://pop/expected.json"))
	var player: AnimationPlayer = node.get_node("AnimationPlayer")
	var sprite: AnimatedSprite2D = node.get_node("Sprite")
	player.callback_mode_method = AnimationMixer.ANIMATION_CALLBACK_MODE_METHOD_IMMEDIATE  # no main loop here
	var fired: Array = []
	if node.has_signal("sprite_event"):
		node.sprite_event.connect(func(event_name, value): fired.append([String(event_name), value]))
	print("autoplay=", player.autoplay, " animations=", player.get_animation_list().size(), " clips=", expected.clips.size())
	var samples := 0
	for clip in expected.clips:
		var name: String = clip.name
		if not player.has_animation(name):
			fail("missing animation " + name)
			continue
		var anim: Animation = player.get_animation(name)
		if absf(anim.length - clip.length) > 0.0001:
			fail("%s length %f, want %f" % [name, anim.length, clip.length])
		if (anim.loop_mode == Animation.LOOP_LINEAR) != clip.loops:
			fail("%s loops %s" % [name, anim.loop_mode])
		var want_next: String = clip.next if clip.next != null else ""
		if String(player.animation_get_next(name)) != want_next:
			fail("%s next %s, want %s" % [name, player.animation_get_next(name), want_next])
		player.clear_queue()
		player.play(name)
		for key in clip["keys"]:
			player.seek(key.t, true)
			samples += 1
			if String(sprite.animation) != key.tag:
				fail("%s at %f shows animation %s, want %s" % [name, key.t, sprite.animation, key.tag])
			var texture: AtlasTexture = sprite.sprite_frames.get_frame_texture(sprite.animation, sprite.frame)
			if texture.region.position != Vector2(key.cell_x, key.cell_y):
				fail("%s at %f shows %s, want (%d, %d)" % [name, key.t, texture.region.position, key.cell_x, key.cell_y])
			for slot in expected.boxes:
				var shape: CollisionShape2D = node.get_node("Hitboxes/" + slot + "/Shape")
				var want = key.boxes.get(slot)
				if want == null:
					if not shape.disabled:
						fail("%s at %f: %s should be off" % [name, key.t, slot])
				elif shape.disabled or not near(shape.position, Vector2(want[0], want[1])) \
						or not near((shape.shape as RectangleShape2D).size, Vector2(want[2], want[3])):
					fail("%s at %f: %s at %s %s, want %s" % [name, key.t, slot, shape.position, (shape.shape as RectangleShape2D).size, want])
			for slot in expected.points:
				var marker: Marker2D = node.get_node("Points/" + slot)
				var want = key.points.get(slot)
				if want == null:
					if marker.visible:
						fail("%s at %f: %s should be hidden" % [name, key.t, slot])
				elif not marker.visible or not near(marker.position, Vector2(want[0], want[1])):
					fail("%s at %f: %s at %s, want %s" % [name, key.t, slot, marker.position, want])
	# Events fire while it plays; a clip that ends goes on with its follow-up.
	for clip in expected.clips:
		var want_events: Array = []
		for key in clip["keys"]:
			for event in key.events:
				want_events.append([event[0], int(event[1])])
		if want_events.is_empty() and clip.next == null:
			continue
		player.stop()
		player.clear_queue()
		fired.clear()
		player.play(clip.name)  # (no seek: the start's events fire once, as in a game)
		var elapsed := 0.0
		while elapsed < clip.length - 0.0001:
			var dt: float = min(1.0 / 240.0, clip.length - 0.0001 - elapsed)
			player.advance(dt)
			elapsed += dt
		var got: Array = []
		for event in fired:
			got.append([event[0], int(event[1])])
		if got != want_events:
			fail("%s fired %s, want %s" % [clip.name, got, want_events])
		if clip.next != null:
			player.advance(0.01)
			if String(player.current_animation) != clip.next:
				fail("%s went on with '%s', want %s" % [clip.name, player.current_animation, clip.next])
	print("CHECKED samples=", samples, " failures=", failures)

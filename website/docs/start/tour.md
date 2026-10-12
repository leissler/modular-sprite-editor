# A tour of the editor

The editor keeps one project open at a time: your images, the modules cut from them, the frames, animations, scenes and mappings. Five tabs show the same project from different sides.

<figure class="ms-shot" markdown="span">
  [![The Frames tab: the frames list and library on the left, a pose on the stage in the middle and the inspector on the right](../assets/images/screens/frames.png)](../assets/images/screens/frames.png)
  <figcaption>The Frames tab. Every tab has the same layout: lists on the left, the canvas in the middle with its view bar below, and the inspector on the right.</figcaption>
</figure>

## The five tabs

**Modules** shows your images. Here you cut them into modules and set each module's pivot, the point that is placed when the module is used in a frame. See [Cut a sheet into modules](../guide/modules.md).

**Frames** is where you build poses from modules and other frames. It also holds the hitboxes and points a game needs. See [Build frames from parts](../guide/frames.md).

**Animations** puts frames in order and times them in ticks. See [Animate](../guide/animations.md).

**Timeline** stages scenes: several objects that move, flip and change their animations over time. See [Stage a scene](../guide/scenes.md).

**Mappings** swaps modules for others to make variants. See [Variants with mappings](../guide/mappings.md).

Switch tabs with the tab bar or with ++cmd+1++ to ++cmd+5++ (++ctrl++ on Windows and Linux).

## The preview mapping

At the top right, **Preview mapping** chooses the mapping every tab shows. Leave it at **<none>** to see the original modules. Choose a mapping to see every frame, animation and scene with its replacements, without changing anything.

## Moving around the canvas

Every canvas works the same way:

- **Zoom** with the mouse wheel, two fingers on a trackpad or a pinch. The zoom glides while you scroll and then settles on a whole pixel size (1×, 2×, 3× and so on), so pixels always stay square.
- **Pan** by holding ++space++ and dragging, by dragging with ++alt++ held, or with the middle mouse button.
- **Fit** everything into view with ++cmd+0++. ++cmd+shift+0++ shows actual pixels.

The view bar under each canvas holds the view options: **Grid** and its size, **Backdrop** (a checkerboard or a colour), **Part bounds**, which outlines every module in a pose, and **Budget**, the [hardware budget overlay](../guide/hardware-budget.md). These only change what you see, never your project.

## Lists

Lists work the same in every tab. **+ New**, **Duplicate** and **Delete** sit under the list. Double-click a name or press ++f2++ to rename it, drag rows to reorder them, and type in **Filter** to find something by name. Thumbnails show what each entry looks like.

## Undo, save and hints

**Undo** (++cmd+z++) and **Redo** (++cmd+shift+z++) work across all tabs: an undo goes back to before your last change, wherever you made it. A drag counts as one change.

The window title shows an asterisk when there are unsaved changes, and the editor asks before closing an unsaved project. Save with ++cmd+s++.

The status bar at the bottom shows hints for the canvas under your mouse and the current zoom. **Help ▸ Keyboard & Mouse Shortcuts** (++cmd+slash++) lists every shortcut, and so does [Keyboard and mouse](../reference/shortcuts.md).

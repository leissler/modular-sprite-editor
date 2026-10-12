# Glossary

**Animation**: a sequence of steps, each showing a frame for a number of ticks.

**Auto Modularize**: a tool that cuts whole sprites into parts they share and rebuilds the frames from them.

**Budget**: the overlay that shows what a pose or scene costs on a Mega Drive in hardware sprites and tiles.

**Easing**: how an object speeds up and slows down between two keys in a scene.

**Event**: a named signal on an animation step, such as a footstep, that the game receives when the step starts.

**Frame**: a pose built from parts. A frame can contain other frames.

**Hardware sprite**: a rectangle of up to 32 by 32 pixels that the Mega Drive can show on its own. A character is made of several.

**Hitbox**: a rectangle on a frame that tells the game where the character can be hit or where it hits.

**Hold**: how many ticks an animation step stays on screen.

**Key**: a stored position, flip, turn and visibility of a scene object at one frame of the scene. A key can also swap the object's image.

**Key colour**: a colour of an image that is treated as transparent.

**Layer**: one object of a scene in the timeline.

**Loop from**: the step where later passes of a looping animation start, so the steps before it play only once.

**Mapping**: a list that swaps some modules for others, or hides them, everywhere at once.

**Module**: one part cut from an image, the building block of frames.

**Onion skin**: faint copies of neighbouring frames or steps, shown to compare poses.

**Origin**: the point of a frame the game positions, usually between the feet.

**Part**: one use of a module or frame inside a frame, with its own position, flip and turn.

**Pivot**: the point of a module that is placed when the module is used in a frame.

**Point**: a marked spot on a frame, such as a hand or the tip of a sword, for the game.

**Preview mapping**: the mapping all tabs show, chosen at the top of the window. It only changes the view.

**Role**: a short name for a hitbox or point, such as `head`, so the game can find it in every frame.

**Root motion**: movement that comes from an animation's step offsets, such as a step forward.

**Scene**: objects on a timeline, moved with keys, for cutscenes or tests.

**SGDK**: the development kit most Mega Drive homebrew games are made with.

**Step**: one entry of an animation: a frame, how long it holds, and its offset, flip and turn.

**Tick**: the unit of animation time. **Tick rate** says how many ticks make a second.

**Tile**: an 8 by 8 pixel block of graphics in the Mega Drive's video memory.

**H40, H32**: the Mega Drive's two screen widths, 320 and 256 pixels, each with its own sprite limits.

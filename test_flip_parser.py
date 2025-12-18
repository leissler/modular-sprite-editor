from models import AuroraSpriteParser, Project
import os

content = """
    ANIM "Turn"
    {
        0x3017
        AF	0x2000	1	-2	0
        AF	0x2000	1	4	0	+FLIP_X
    }
"""

project = AuroraSpriteParser.parse(content, ".")
print(f"Anims: {len(project.animations)}")
for anim in project.animations:
    print(f" - {anim.name}")
    for i, af in enumerate(anim.aframes):
        print(f"   AF[{i}] flip_x={af.flip_x}")

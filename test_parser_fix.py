from models import AuroraSpriteParser, Project
import os

content = """
    MODULES
    {
        MD	0x1009	MD_IMAGE	0	0	1	1	1
        MD	0x10AD	MD_IMAGE	0	597	859	27	19	"_00"
    }

    FRAME "wait"
    {
        0x2000
        FM	0x1023	-16	-37
    }
"""

project = AuroraSpriteParser.parse(content, ".")
print(f"Modules: {len(project.modules)}")
for m in project.modules:
    print(f" - {m.id}: '{m.name}'")

print(f"Frames: {len(project.frames)}")
for f in project.frames:
    print(f" - {f.id}: '{f.name}'")


import os
from models import Project, Module, ImageAsset

def test_serialization():
    p = Project()
    img = p.create_image("/tmp/test.png", 100, 100)
    mod = p.create_module("TestMod", img.id, (0, 0, 32, 32), (16, 16))
    
    json_path = "test_project.json"
    p.to_json(json_path)
    
    p2 = Project.from_json(json_path)
    
    assert len(p2.images) == 1
    assert p2.images[0].file_path == "/tmp/test.png"
    assert len(p2.modules) == 1
    assert p2.modules[0].name == "TestMod"
    
    print("Serialization test passed!")
    if os.path.exists(json_path):
        os.remove(json_path)

if __name__ == "__main__":
    test_serialization()

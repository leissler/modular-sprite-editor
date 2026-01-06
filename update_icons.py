import os
import subprocess
import sys
from PIL import Image

def generate_icons(source_path="assets/icon_source.png"):
    if not os.path.exists(source_path):
        print(f"Error: Source image not found at {source_path}")
        print("Please save your new icon design as 'assets/icon_source.png' and try again.")
        return

    print(f"Processing {source_path}...")
    img = Image.open(source_path)

    # 1. Generate Windows ICO (Multi-layer)
    print("Generating assets/icon.ico...")
    sizes_ico = [256, 128, 64, 48, 32, 16]
    resampled_ico = []
    for s in sizes_ico:
        resampled_ico.append(img.resize((s, s), Image.Resampling.LANCZOS))
    
    resampled_ico[0].save('assets/icon.ico', format='ICO', append_images=resampled_ico[1:])
    print("  -> Done.")

    # 2. Generate MacOS ICNS (via iconset)
    # This requires 'iconutil', available only on macOS.
    if sys.platform == 'darwin':
        print("Generating assets/icon.icns...")
        iconset_dir = 'assets/icon.iconset'
        os.makedirs(iconset_dir, exist_ok=True)

        # MacOS Iconset Specs
        mac_sizes = [
            ('icon_16x16.png', 16),
            ('icon_16x16@2x.png', 32),
            ('icon_32x32.png', 32),
            ('icon_32x32@2x.png', 64),
            ('icon_128x128.png', 128),
            ('icon_128x128@2x.png', 256),
            ('icon_256x256.png', 256),
            ('icon_256x256@2x.png', 512),
            ('icon_512x512.png', 512),
            ('icon_512x512@2x.png', 1024)
        ]

        for name, size in mac_sizes:
            r = img.resize((size, size), Image.Resampling.LANCZOS)
            r.save(os.path.join(iconset_dir, name))

        try:
            subprocess.run(['iconutil', '-c', 'icns', iconset_dir], check=True)
            print("  -> Done.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("  -> Warning: 'iconutil' failed or not found. skipping .icns generation.")
    
    else:
        print("Skipping .icns generation (requires macOS). The Windows .ico is ready.")

if __name__ == "__main__":
    # If args provided, use that
    src = "assets/icon_source.png"
    if len(sys.argv) > 1:
        src = sys.argv[1]
    
    # Check if we should rename current icon.png to source if source missing?
    # No, let's keep it simple.
    # If assets/icon_source.png doesn't exist but assets/icon.png does, use that
    if not os.path.exists(src) and os.path.exists("assets/icon.png"):
        print(f"'{src}' not found, using 'assets/icon.png' instead.")
        src = "assets/icon.png"

    generate_icons(src)

"""Generate a separate integrated UAV script without overwriting upstream files."""
import argparse
import ast
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('repo', type=Path)
args = parser.parse_args()
source = (args.repo / 'scripts/uav_vo.py').read_text()
replacements = [
    ('    mtx_server.start()\n', '    if mtx_cfg.get("auto_start", True):\n        mtx_server.start()\n'),
    ('import argparse\n', 'import argparse\nfrom datetime import datetime, timezone\nfrom frame_bridge import FrameBridge\n'),
    ('    t_idx = 0\n', '    bridge = FrameBridge(os.environ.get("FRAME_DIR", "./logs/frame-bundles"), interval=1.0)\n    t_idx = 0\n'),
    ('                last_seq = seq\n', '                received_at = datetime.now(timezone.utc).isoformat()\n                last_seq = seq\n'),
    ('                jpeg_kb = len(jpeg_bytes)', '''                # Latest keyframe pose is context, not a synchronized pose for this image.
                # Monocular translation scale is unknown; do not label these values meters.
                context = {"producer": "beagle_eyes", "odometry_initialized": bool(slam.is_initialized)}
                if slam.is_initialized and slam.n > 0:
                    context["latest_keyframe_pose"] = {
                        "translation": [float(v) for v in pose[:3]],
                        "quaternion_xyzw": [float(v) for v in pose[3:7]],
                        "units": "arbitrary_monocular_scale",
                        "transform": "camera_to_world",
                        "association": "latest_keyframe_not_necessarily_this_image",
                    }
                bridge.save(frame, seq, context, received_at)

                jpeg_kb = len(jpeg_bytes)'''),
]
for old, new in replacements:
    if source.count(old) != 1:
        raise SystemExit('Upstream script changed; review the integration rather than applying blindly.')
    source = source.replace(old, new)
ast.parse(source)
target = args.repo / 'scripts/uav_vo_firesight.py'
helper = args.repo / 'scripts/frame_bridge.py'
if target.exists() or helper.exists():
    raise SystemExit('Generated script or helper already exists; review rather than overwriting.')
target.write_text(source)
shutil.copyfile(Path(__file__).resolve().parents[1] / 'integrations/beagle_eyes/frame_bridge.py', helper)
print(f'Created {target}; original uav_vo.py unchanged.')

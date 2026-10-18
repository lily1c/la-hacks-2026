"""Generate a separate UAV entrypoint; preserve Greg's original script."""
import ast
from pathlib import Path
import shutil
import sys
root=Path(sys.argv[1]).expanduser()
source=(root/'scripts/uav_vo.py').read_text()
changes=[
 ('import argparse\n','import argparse\nfrom firesight_export import FireSightExport\n'),
 ('    frames_total = 0\n','    exporter = FireSightExport()\n    frames_total = 0\n'),
 ('                jpeg_kb = len(jpeg_bytes)', '''                exporter.update(jpeg_bytes, seq, int(frame.shape[1]), int(frame.shape[0]),
                                slam.is_initialized and slam.n > 0,
                                (x, y, z) if slam.is_initialized and slam.n > 0 else None)
                jpeg_kb = len(jpeg_bytes)'''),
 ('        mtx_server.stop()','        exporter.close()\n        mtx_server.stop()')]
for old,new in changes:
 if source.count(old)!=1: raise SystemExit('Upstream changed; review required: '+old.strip())
 source=source.replace(old,new)
ast.parse(source)
target=root/'scripts/uav_vo_dashboard.py'
helper=root/'scripts/firesight_export.py'
if target.exists() or helper.exists(): raise SystemExit('Adapter already exists; refusing overwrite')
target.write_text(source)
shutil.copyfile(Path(__file__).with_name('firesight_export.py'),helper)
print('Created', target)

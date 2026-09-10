"""Bundle the tested Blender scene, original object PLYs, and offline installer."""
from pathlib import Path
from zipfile import ZipFile,ZIP_STORED,ZIP_DEFLATED
import json,shutil,hashlib
root=Path(__file__).resolve().parents[2];r=root/'outputs/images/A_MARCEAU/gaussian_editable';d=r/'delivery';d.mkdir(exist_ok=True)
official=d/'3dgs_render_by_kiri_engine_4.1.5.zip'
if not official.exists():official.symlink_to(root/'.tools/downloads/3dgs_render_by_kiri_engine_4.1.5.zip')
for name in ['scene.blend','partition.json','source_manifest.json','viewer_startup_camera.json','partition_integrity.json']:
 target=d/name
 if target.is_symlink():continue
 shutil.copy2(r/name,target)
with ZipFile(d/'mapmaker_gaussian_scene.zip','w',compression=ZIP_DEFLATED) as z:z.write(root/'blender_addons/mapmaker_gaussian_scene/__init__.py','mapmaker_gaussian_scene/__init__.py')
shutil.copy2(root/'scripts/gaussian_scene/install_blender_package.py',d/'install_blender_package.py');shutil.copy2(root/'third_party/licenses/KIRI_GPL-3.0.txt',d/'KIRI_LICENSE')
readme='''A_MARCEAU — 객체별 원본 Gaussian 장면

Blender 4.5 LTS(실제 검증: 4.5.3)에서 사용하는 장면입니다.
이 패키지는 일반 후처리 메시가 아니라 학습 원본 Gaussian 외관을 보존합니다.

처음 설치
1. ZIP 전체를 같은 폴더에 풉니다.
2. Blender 4.5 LTS를 엽니다.
3. Scripting 작업 공간 → Text/Open으로 install_blender_package.py를 엽니다.
4. Run Script(Alt+P)를 누릅니다. 동봉한 두 애드온을 사용자 설정에 설치하고 장면을 엽니다.
5. 이후에는 scene.blend를 바로 열면 됩니다.
인터넷, Hugging Face 인증, 원래 프로젝트 경로는 필요 없습니다.
Blender가 이미 설치되어 있어야 합니다. 이 패키지는 Blender 실행 파일을 포함하지 않습니다.

편집
- Outliner에서 객체를 골라 G/R/S로 이동·회전·크기를 바꿉니다.
- 건물에 속한 문/기둥은 부모 건물의 변환을 함께 따릅니다.
- 계층 전체 삭제는 Outliner의 Delete Hierarchy를 사용합니다.
- 계층 전체 복제는 부모와 자식을 함께 선택한 뒤 Shift+D를 사용합니다.
- 단독 객체는 일반 Shift+D/X를 사용합니다. 독립 재질 편집에는 재질도 Single User로 복제합니다.
- 형상은 Gaussian 중심점/크기/회전 속성으로 저장됩니다. Edit Mode의 점 편집과 Mesh Attributes를 사용합니다.
- 시작 화면에서 선택 표시를 숨겼습니다. 점을 편집할 때 Viewport Overlays를 켭니다.
- Appearance 재질의 Principled BSDF Base Color와 Alpha는 원본 Gaussian 색/불투명도에 곱해집니다.
- 파일 저장은 Blender의 일반 Save/Save As를 사용합니다.

표현의 범위
Gaussian 중심점을 담은 Blender Mesh이며 폴리곤 면/UV를 가진 리토폴로지 메시가 아닙니다.
PBR 거칠기·금속성 변경으로 장면 전체를 재조명하는 표현은 아닙니다.
도로·배경 및 객체로 확정되지 않은 Gaussian은 Environment에 보존됩니다.
작은 물체와 가려진 경계에는 자동 분리 오차가 남아 있습니다. 모든 실제 객체의 완전 분리를 보증하지 않습니다.
원본에 없는 뒷면이나 학습 결과 자체의 결손은 새로 생성하지 않았습니다.
Unity/Unreal 가져오기는 여기서 실행 검증하지 않았습니다.

파일
scene.blend: 처음 배치와 원본 속성이 내장된 장면.
objects_refined/: 각 객체의 원본 Gaussian PLY와 원본 인덱스, 관측 근거.
partition.json: 객체/부품 관계와 파일 경로.
partition_integrity.json: 누락·중복 및 원본 속성 대조 결과.
3dgs_render_by_kiri_engine_4.1.5.zip: 공식 KIRI 배포 원본(별도 GPL 라이선스).
mapmaker_gaussian_scene.zip: Blender 편집 상태를 Gaussian 렌더에 연결하는 애드온.

KIRI 원본: https://github.com/Kiri-Innovation/3dgs-render-blender-addon/releases/tag/v4.1.5
원본 ZIP SHA256: ea8366fe0708d8bb69ec3b3fb4e8b08b721fb309c3f71db04b6f49f56b70ba03
'''
(d/'읽어주세요.txt').write_text(readme)
for name in ['final_visual_comparison.json','final_visual_comparison.jpg','startup_check.json','startup_viewport.png']:
 if (r/name).exists():shutil.copy2(r/name,d/name)
for name in ['report.json','hierarchy_report.json']:
 if (r/'edit_validation'/name).exists():shutil.copy2(r/'edit_validation'/name,d/('edit_'+name))
archive=r/'A_MARCEAU_Blender_Gaussian.zip'
archive_tmp=archive.with_suffix('.zip.tmp')
with ZipFile(archive_tmp,'w',allowZip64=True) as z:
 for path in sorted(d.iterdir()):
  if path.is_file():z.write(path,path.name,compress_type=ZIP_STORED if path.suffix=='.zip' else ZIP_DEFLATED,compresslevel=1)
 for obj in json.loads((r/'partition.json').read_text())['objects']:
  folder=(r/obj['ply']).parent
  for name in ['gaussians.ply','source_gaussian_ids.npy','observations.json','reference.png']:
   path=folder/name
   if path.is_file():z.write(path,path.relative_to(r),compress_type=ZIP_DEFLATED,compresslevel=1)
with ZipFile(archive_tmp) as z:
 bad=z.testzip()
 if bad:raise RuntimeError('ZIP CRC failed: '+bad)
archive_tmp.replace(archive)
with archive.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
(r/'delivery_manifest.json').write_text(json.dumps(dict(file=archive.name,bytes=archive.stat().st_size,sha256=sha,blender='4.5.3 LTS',objects=len(json.loads((r/'partition.json').read_text())['objects'])),indent=2));print('DELIVERY_PACKAGE',archive,archive.stat().st_size,flush=True)

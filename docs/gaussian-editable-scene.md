# 원본 Gaussian 객체 장면 — A_MARCEAU

결과 위치는 `outputs/images/A_MARCEAU/gaussian_editable/`다. `scene.blend`는 원본 학습 체크포인트의 Gaussian 3,362,050개를 보존한다. 145개 Gaussian 데이터 객체를 91개 최상위 편집 단위, 53개 하위 부품, Environment로 구성했다. 이는 수동 확정한 실제 물체 개수가 아니다.

## 확인된 품질과 편집

- 원본 PLY와 객체별 PLY의 모든 원시 속성을 바이트 단위로 대조했다. 누락 0, 중복 0. Blender의 로컬 원점 변환에서 float32 최대 오차는 약 4.77e-7이다.
- 웹뷰어의 시작 카메라와 같은 832×480 시점에서 gsplat 원본과 Blender KIRI 렌더의 PSNR은 40.99 dB다. `final_visual_comparison.jpg`와 JSON에 비교를 남겼다. 이 수치는 한 시점의 외관 비교이며 전 시점의 픽셀 일치를 보장하지 않는다.
- 실제 저장 파일을 다시 열어 독립 이동/회전/크기, 숨김, 복제, 점 위치/색상 속성, 표준 재질 Base Color/Alpha, 삭제를 검증했다. 다른 객체의 데이터와 변환은 유지됐다.
- 부모 건물과 하위 부품의 동반 변환, Blender 기본 복제 명령의 계층 재연결과 독립 데이터, 계층 삭제, 일반 메시 교체의 실제 화면 표시를 검사했다. `edit_validation/report.json`, `hierarchy_report.json`에 결과가 있다.
- 기본 복제·삭제에서 손상되던 바이너리 ID 속성 캐시는 제거했다. bridge v0.3은 Mesh를 저장 원본으로 삼고 실행 중에만 렌더 캐시를 만든다. 데이터 손실 없이 blend 파일이 약 185 MB로 줄었다.

## 사용

`A_MARCEAU_Blender_Gaussian.zip` 전체를 풀고 Blender 4.5 LTS에서 동봉한 `install_blender_package.py`를 Text Editor로 열어 실행한다. 공식 KIRI 4.1.5와 MapMaker bridge를 설치하고 장면을 연다. 이후에는 `scene.blend`를 바로 연다. 설치 안내는 동봉한 `읽어주세요.txt`에 있다.

Pod에서 준비된 환경으로 실행:

```bash
cd /workspace/MapMaker
bash scripts/start-blender-editable.sh
```

GUI 디스플레이가 필요하다. 검증은 Xvfb/llvmpipe에서 했으며 사용자 GPU 성능 측정은 아니다. `.tools/`, `.venvs/`, `outputs/`는 workspace에 보관된다. 재시작으로 사라지는 OS의 xvfb·공유 라이브러리는 다시 준비해야 할 수 있다.

## 분리 방식과 남은 한계

`objects.json`을 프롬프트로 사용해 원본 Gaussian을 808개 보정 카메라에서 렌더하고 SAM3로 재탐지했다. 10,731개 마스크를 실제 Gaussian의 픽셀 기여도에 대응했다. 같은 시점의 서로 다른 물체가 합쳐지지 않도록 제약을 적용하고, 원본 형상·외관 속성은 고정한 채 Gaussian의 객체 소속만 최적화했다.

64개 시점에서 자동 SAM3 마스크와 비교한 평균 객체 IoU는 0.277에서 0.402로 개선됐다. 사람이 만든 정답과의 정확도가 아니며, 작은 물체·가림·잘못된 탐지에는 경계 오차와 조각이 남는다. 도로·배경과 미확정 Gaussian 1,944,452개는 Environment에 보존한다. 모든 실제 물체의 완전 분리가 검증됐다고 해석하면 안 된다.

표현은 Gaussian 중심점과 속성을 담은 Blender Mesh다. 폴리곤 면/UV가 있는 리토폴로지 메시가 아니다. 기본 변환과 Gaussian 점·속성 수정, 색/투명도 변경을 지원한다. PBR 거칠기·금속성에 따른 재조명, 미관측 뒷면 생성, Unity/Unreal 가져오기는 검증 범위 밖이다.

## 재현과 출처

`scripts/run-gaussian-object-scene.sh`가 A_MARCEAU의 내보내기부터 분리·Blender 검증·패키징까지 연결한다. 각 단계는 실행했지만 최신 통합 스크립트 전체를 처음부터 다시 실행하지는 않았다. 중간 결과와 이전 실패 실험은 보존했다.

공식 KIRI 배포: https://github.com/Kiri-Innovation/3dgs-render-blender-addon/releases/tag/v4.1.5

배포 ZIP SHA256: `ea8366fe0708d8bb69ec3b3fb4e8b08b721fb309c3f71db04b6f49f56b70ba03`. 원본 라이선스 고지를 패키지에 포함한다.

## 새 체크아웃의 선행 준비

이 커밋은 모델이나 장면 데이터를 포함하지 않는다. 기존 프로젝트 환경 설치 후 다음 파일을 준비해야 한다.

- `.venvs/main`: CUDA PyTorch, gsplat, transformers(SAM3 API), scipy, plyfile, Pillow(ImageGrab 포함).
- `.cache/huggingface`: `facebook/sam3` 모델과 프로세서. 탐지는 `local_files_only=True`로 실행한다.
- `outputs/images/A_MARCEAU/`: `objects.json`, `gs/ckpts/ckpt_7999_rank0.pt`, `gs_data/cameras.json`과 해당 `images/*.png`.
- `.tools/blender/blender-4.5.3-linux-x64/blender`: Blender 4.5.3 Linux 실행 파일.
- `.tools/downloads/3dgs_render_by_kiri_engine_4.1.5.zip`: 위 공식 릴리스 ZIP. 설치 스크립트가 SHA256을 확인한다.
- OS의 Xvfb 및 Blender에 필요한 공유 라이브러리.

```bash
bash scripts/setup-gaussian-blender.sh
bash scripts/run-gaussian-object-scene.sh
```

첫 스크립트는 로컬 ZIP에서 애드온을 설치하고 사용자 설정을 저장한다. 네트워크 다운로드는 하지 않는다. KIRI 소스 저장소를 별도로 복제할 필요는 없으며 라이선스는 `third_party/licenses/KIRI_GPL-3.0.txt`에 보존했다. 실행 중 필요한 주요 파일·모듈은 장시간 처리 전에 확인한다.

리포지토리 절대 경로는 스크립트 위치에서 계산한다. 장면 이름과 일부 검증 조건·검토된 부품 관계는 A_MARCEAU 전용이며 범용 장면 지원으로 주장하지 않는다. 새 머신의 모든 의존성 설치부터 전체 재생성까지는 아직 일괄 검증하지 않았다.

<!-- Author: Codex (IIC) -->
# 헤드 D435i로 계단 치수 측정하기

`g1 stairs measure`는 정지한 G1-EDU에서 기록한 깊이 영상으로 각 수평면의 높이, 단차, 디딤면 깊이와 폭을 미터 단위로 추정한다. `g1 stairs assess`는 같은 깊이 프레임에서 발을 놓을 수 있는 후보와 입력한 도달 조건을 검사한다. 두 명령 모두 저장된 파일만 읽어 계산한다.

## 1. 움직이지 않는 자세에서 깊이 기록하기

기체와 카메라 자세를 고정한다. 정면에서 계단을 보고 첫 단 앞의 바닥, 단의 앞·뒤 모서리, 좌우 끝이 영상에 들어오도록 한다. 카메라를 움직여야 하면 별도 기록을 시작하고 해당 자세의 보정을 쓴다. 운영 컨테이너 준비와 USB 장치 선택은 [G1 호스트 설치 절차](../README.md#create)를 따른다.

**G1 호스트 · 사용할 터미널마다 같은 운영 컨테이너 열기**

```bash
docker exec -it jsj-g1-tools bash
```

**컨테이너 내부 · 터미널 A에서 영상 경로 확인**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
g1 camera check --seconds 5
```

`eth0`와 도메인 `0`은 연구실 구성이다. 이미 헤드 카메라의 ROS 2 깊이 영상이 수신된다면 그 발행기를 유지한다. 직접 연결한 D435i가 보이고 사용 가능한 경우 아래 명령으로 발행한 뒤 터미널 A를 열어 둔다. `rt/frontvideostream`의 writer 발견, 압축 컬러 영상, 또는 `DDS_NO_SAMPLES`만으로는 계단 측정에 필요한 원시 깊이와 보정값을 얻을 수 없다. [검사 결과 해석과 영상 확인](camera-check.md)

**컨테이너 내부 · 터미널 A에서 USB 카메라의 깊이 발행이 필요할 때**

```bash
g1 camera start --stream depth
```

**컨테이너 내부 · 터미널 B에서 위 발행기의 깊이를 5초 기록**

```bash
export G1_CAMERA_IFACE=eth0 G1_CAMERA_DOMAIN=0
RUN_ID="stairs-$(date +%Y%m%d-%H%M%S)"
g1 camera record-ros --run "$RUN_ID" --seconds 5 \
  --depth-topic /g1/head/depth/image_rect_raw \
  --info-topic /g1/head/depth/camera_info --depth-scale-m 0.001
```

위 발행기는 RealSense SDK에서 장치 단위를 읽어 ROS 영상의 각 정수를 **밀리미터**로 환산한다. 예를 들어 픽셀값 `750`은 광학축 방향 깊이 `0.750 m`다. 다른 발행기라면 해당 발행기의 깊이 단위를 확인해 `--depth-scale-m`에 넣고 토픽 두 개도 바꾼다. 기록기는 깊이 카메라 자체 좌표계에서 정류된 `16UC1` 이미지와 동일 촬영 시각·동일 `frame_id`의 `CameraInfo`를 짝지어 저장한다. 컬러에 정렬한 깊이나 화면 미리보기 PNG는 이 입력 규격에 맞지 않는다.

**컨테이너 내부 · USB에서 직접 기록하는 경우**

```bash
g1 camera probe-usb
RUN_ID="stairs-usb-$(date +%Y%m%d-%H%M%S)"
g1 camera record --run "$RUN_ID" --seconds 5
```

USB 직접 기록은 카메라를 점유하는 발행기가 없을 때 선택한다. 자신이 터미널 A에서 시작한 발행기는 Ctrl+C로 종료할 수 있다. 직접 기록 기본값은 640×480, 60 Hz, Z16이다. `probe-usb`에 나온 프로필에 따라 `--width`, `--height`, `--fps`를 변경할 수 있다. 깊이 단위는 SDK의 `depth_frame.get_units()`에서 읽는다.

**컨테이너 내부 · 기록한 셸에서 데이터와 광학 프레임 확인**

```bash
g1 camera replay --run "$RUN_ID"
python3 -m json.tool "/workspace/runs/$RUN_ID/depth/manifest.json"
```

`frame_count`, `invalid_depth_fraction`, `min_depth_m`, `max_depth_m`로 유효 깊이가 들어왔는지 확인한다. `invalid_depth_fraction=1`이면 모든 픽셀이 결측이다. 이후 단계에서 쓰는 `source_frame`은 이 manifest의 `frame_id`다. 새 셸에서 이어갈 때는 `RUN_ID`에 같은 기록명을 다시 지정한다. [Windows에서 영상 보기](remote-camera.md)

## 2. 실측한 깊이 광학 좌표 → 중력 좌표 변환 준비하기

측정기는 `p_중력 = rotation × p_광학 + translation_m`을 적용한다. 깊이 광학 좌표는 오른쪽·아래·전방 순서다. 현장 좌표는 **x가 계단 진행 방향, y가 왼쪽, z가 위**가 되도록 잡는다. 단이 x축과 비스듬하면 x·y 방향으로 구한 폭과 깊이가 실제 디딤면의 폭·깊이와 달라진다. [RealSense 투영과 좌표 규약](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

1. 기준 바닥에 원점과 계단 진행 방향을 표시하고 수평·수직을 실측한다. 바닥을 `z=0`으로 정의했다면 `ground_z_m`은 `0`이다. 영상에 보이는 기준점들의 현장 좌표를 미터로 측정한다. 서로 한 직선에 놓이지 않게 분산하고 가능하면 높이와 거리도 다르게 한다.
2. 같은 고정 자세에서 기준점의 **깊이 영상** 픽셀과 유효 깊이를 대응시킨다. 같은 프로필의 `intrinsics` 및 `depth_scale_m`로 공식 SDK `rs2_deproject_pixel_to_point`를 적용하면 각 기준점의 광학 좌표가 나온다. 깊이값 `0`, 가려진 점, 모서리에서 전경·배경 깊이가 섞이는 점은 제외한다.
3. 대응점 3개 이상으로 두 점군 사이의 강체변환을 구한다. 예를 들어 두 점군의 중심을 뺀 뒤 SVD로 회전 `R`을 적합하고 `det(R)=+1`을 확인한다. 이동은 `t = 현장 좌표 중심 − R × 광학 좌표 중심`이다. 독립적인 기준점과 바닥을 남겨서 변환 방향, 바닥의 높이·기울기, 줄자로 잰 단차·폭과의 오차를 확인한다. 실험에 필요한 정밀도를 충족한 자세에서만 이 보정을 재사용한다.
4. [보정 JSON 형식](../config/calibration.example.json)의 `source_frame`, `frame_id`, `rotation`, `translation_m`, `ground_z_m`에 얻은 값을 넣는다. `translation_m`은 현장 좌표에서의 광학 중심 위치다. 예제의 카메라 높이·회전은 서식 설명용이다. `ground_z_m`을 모르면 필드를 생략할 수 있으며 첫 단의 바닥 기준 높이도 미확정으로 남는다.

<a id="calibrate"></a>

### 한 프레임의 실측 대응점으로 보정 파일 만들기

현장 기준 바닥을 `z=0`으로 정한 예시다. 깊이 영상에서 식별할 수 있는 기준점을 사용한다. 기본은 첫 프레임이다. 다른 프레임을 쓰려면 첫 명령에 `--frame-number N`을 추가한다. USB의 장치 프레임 번호는 `.npy` 파일명의 일련번호와 다를 수 있다.

**컨테이너 내부 · 기록한 셸에서 원래 픽셀 크기의 PNG 저장**

```bash
DIR="/workspace/runs/$RUN_ID"
g1 stairs calibrate --run "$RUN_ID"
```

출력에 사용한 `frame_number`와 `pixels-<프레임번호>.png` 경로가 표시된다. PNG를 원래 크기로 열어 각 기준점의 열 `u`(오른쪽 증가), 행 `v`(아래 증가)를 읽는다. 좌측 상단은 `(0,0)`이다. Windows에서 파일을 열려면 [PNG 열기 안내](camera-check.md#usb-깊이-미리보기)의 HTTP 서버 `--directory`를 `"$DIR"`로 지정하고, SSH 포트 전달 뒤 브라우저에서 `pixels-<프레임번호>.png`를 연다. 이미지 편집기에서 픽셀 좌표를 읽을 수도 있다. 계산에는 같은 번호의 원본 Z16을 쓴다.

**컨테이너 내부 · 선택한 픽셀과 현장 실측 좌표를 CSV로 입력**

```bash
read -rp 'PNG에 쓴 frame_number: ' FRAME
PAIRS="$DIR/points-$FRAME.csv"
( set -C; { echo 'use,u,v,x_m,y_m,z_m'; cat; } > "$PAIRS" )
```

헤더는 명령이 작성한다. 각 점에 대해 `fit,u,v,x_m,y_m,z_m`의 여섯 칸을 실제 값으로 입력하고, 변환 적합에서 제외할 독립점은 첫 칸에 `check`를 쓴다. 쉼표로 구분하고, 한 줄에 한 점을 입력한 뒤 새 줄에서 Ctrl+D를 누른다. 일직선상에 있지 않은 `fit` 점 3개 이상과 `check` 점 1개 이상이 필요하다. 둘 다 영상에 넓게 분포시킨다.

**컨테이너 내부 · SDK로 광학 좌표 복원, 회전·이동 계산 및 독립점 검증**

```bash
CAL="$DIR/measured-calibration.json"
g1 stairs calibrate --run "$RUN_ID" --frame-number "$FRAME" \
  --points "$PAIRS" --ground-z-m 0 --output "$CAL"
```

`fit_rmse_m`은 적합에 사용한 점들의 위치 오차를 제곱해 평균을 구한 뒤 제곱근을 취한 값이다(미터). `check_points`에서는 적합에 쓰지 않은 각 점의 예측 좌표 `estimated_m`, 실측 좌표 `surveyed_m`, 두 점 사이 거리 `error_m`를 직접 비교한다. 오차가 실험에 필요한 정밀도보다 크거나 기준 바닥·계단 방향 확인에 실패하면 점 대응과 센서 자세를 확인한 뒤 새 `--output`으로 다시 보정한다. 결과는 덮어쓰지 않는다. 바닥 높이를 모르면 `--ground-z-m`을 생략한다. 같은 자세의 실측 JSON이 있으면 `CAL`에 그 경로를 바로 넣을 수 있다. `record` 또는 `record-ros`에서 `--calibration`을 지정한 경우 해당 기록의 `depth/calibration.json`에도 저장된다.

## 3. 치수 계산과 판독

**컨테이너 내부 · 위 셸에서 첫 프레임 측정 후 전체 결과 읽기**

```bash
g1 stairs measure --run "$RUN_ID" --calibration "$CAL"
head -n 1 "/workspace/runs/$RUN_ID/geometry/stairs.jsonl" | python3 -m json.tool
```

기록에 보정을 포함했다면 `--calibration "$CAL"`을 생략한다. 기본값은 첫 프레임이다. 특정 프레임은 `--frame-number N`에 `depth/frames.jsonl`의 `frame_number`를 넣고, 같은 자세의 모든 프레임을 각각 측정하려면 첫 실행 때 `--all-frames`를 추가한다. 기존 `geometry/`는 보존한다. 같은 깊이에 다른 설정을 비교할 때는 새 실험 디렉터리에 `depth/`를 복사한 뒤 새 `--run`을 지정한다. 프레임별 결과는 `geometry/stairs.jsonl`, 사용한 보정·옵션은 `geometry/manifest.json`에 저장된다.

| 출력 | 읽는 법 |
| --- | --- |
| `status`, `ground_observed`, `treads` | `surfaces_observed`는 하나 이상의 수평면 후보를 찾았다는 뜻이다. 바닥만 보여도 이 상태가 나오며 `treads`는 빈 배열일 수 있다. 책상 등 다른 수평면도 후보에 포함될 수 있다. `no_horizontal_surfaces`는 후보가 없다는 뜻이다. |
| `z_m`, `height_above_reference_ground_m` | 각각 면 높이의 중앙값과 입력한 기준 바닥 높이와의 차이다. 기준 바닥 높이를 입력해도 실제 바닥 관측 여부는 `ground_observed`로 따로 확인한다. |
| `riser_height_m`, `signed_height_change_m`, `riser_status` | `riser_height_m`은 추정 단차의 절댓값이다. 부호 있는 변화량은 진행 방향으로 다음 면이 높아지면 양수다. 첫 면 바로 앞에서 바닥을 관측하면 `estimated_from_ground`, 인접한 두 면의 경계 근거가 있으면 `estimated_common_boundary`, 근거가 부족하면 `boundary_unconfirmed`와 `null`이 나온다. |
| `tread_depth_m`, `width_m`, `edges` | 앞·뒤 두 경계를 추정한 경우에만 깊이, 좌·우 두 경계를 추정한 경우에만 폭이 나온다. 예를 들어 `width_m: null`은 폭 미확정이다. `edges`는 방향별 `observed_transition` 또는 `unconfirmed`, 위치와 근거 샘플 수를 남긴다. |
| `observed_tread_depth_span_m`, `observed_width_span_m`, `observed_cells` | 관측된 점들의 x·y 범위와 관측된 격자 좌표다. 격자는 원점 `(0,0)`에서 시작하며 셀 `(i,j)`의 중심은 `((i+0.5)×grid_m, (j+0.5)×grid_m)`이다. 두 끝 사이에 결측 구멍이 있을 수 있다. |
| `dimension_status`, `height_mad_m`, `horizontal_sample_count` | 깊이와 폭이 모두 나왔으면 `edge_estimates`, 한 축이라도 미확정이면 `partial_boundaries`다. 높이의 중앙절대편차와 수평 샘플 수는 관측 품질을 살피는 값이다. 미터 단위 MAD는 측정 정확도나 보행 성공 확률을 나타내지는 않는다. |

기본값은 격자 변 `--grid-m 0.025`(2.5 cm), 높이 묶음 허용차 `--height-tolerance-m 0.018`(1.8 cm), 연결 성분 최소 표본 `--min-samples 45`다. 구현은 행·열 이웃의 기울기 기준 12°와 높이 허용분을 적용하고, 같은 높이대에서 연결되고 5개 이상의 격자를 차지하는 면을 추출한다. 각 끝의 경계 위치에는 적어도 5개의 전이 근거와 모서리 방향으로 분포한 관측이 필요하다. 이 값들은 영상 분석용이며 G1의 허용 단차·최대 경사 사양과 별개다. 한쪽 끝이 가려지면 자세와 시야를 바꾼 별도 정지 기록으로 확인한다. [측정 구현](../src/g1stairs/geometry/surfaces.py) · [합성 계단·가림·결측 회귀시험](../src/g1stairs/geometry/test_geometry.py)

현장 정확도를 확인할 때는 같은 단의 높이·깊이·폭을 줄자로 따로 재고, 프레임 번호와 함께 각 축의 추정값·실측값·절대오차를 기록한다. 경계 부족으로 나온 `null`은 치수 오차 평균에서 빼고, 전체 단 중 몇 단에서 측정할 수 있었는지 함께 기록한다. 현재 이 저장소에는 연구실 G1에서 실측값과 대조한 계단 오차 기록이 없다.

## 연속 계단과 단 경계 간격 판독

Pérez-Yus 등의 연구는 수평면 후보를 연결하고 연속 단 경계 사이의 수평 거리를 측정한다. 이 프로젝트는 보정한 계단 진행축에서 높이가 다른 두 면의 경계 근거와 경계 주변의 공통 관측 셀을 확인한다. 높이가 한 방향으로 변하는 면 세 개 이상이 갈림길 없이 연결되면 `stair_flights`에 면 번호, 오르막·내리막 방향, 연결 근거를 기록한다. 앞 단 또는 다음 단에 경계 근거가 있어야 하며 가려진 중간 단은 건너뛰지 않는다. 프로젝트에서 이 방법을 격자와 중앙값으로 구현했다. [CVIU 논문 §4](https://webdiis.unizar.es/~glopez/papers/Perez-YusCVIU2017.pdf) · [저자들의 면 연결 코드](https://github.com/aperezyus/stairs_detection/blob/0a8a6272a9916444a4bda19c167f5a912f42c65f/src/stair/current_scene_stair.cpp#L107-L190) · [저자들의 치수 계산 코드](https://github.com/aperezyus/stairs_detection/blob/0a8a6272a9916444a4bda19c167f5a912f42c65f/src/stair/stair_classes.cpp#L300-L365)

`median_riser_height_m`은 연결된 단차의 중앙값이다. `median_going_m`은 연속으로 관측한 단 경계 사이의 수평 간격의 중앙값이다. 디딤면의 물리적 앞뒤 깊이는 그 면의 `tread_depth_m`에서 확인한다. 돌출된 코나 가려진 모서리가 있으면 두 값의 의미가 달라진다. 각 중앙값에는 사용한 표본 수와 중앙절대편차가 함께 나온다. 수평면 하나만 관측하면 해당 면의 정보는 남고 `stair_flights`는 비어 있다.

## 저장된 면에서 한 발의 지지와 도달 검사

Griffin 등은 후보 발바닥과 관측한 평면의 겹침을 이용해 휴머노이드의 발 디딤 후보를 평가했다. 이 프로젝트는 측정한 발 외곽을 감싸는 직사각형을 사용한다. 발의 방향, 가장자리 여유, 위치·방향 오차를 적용한 뒤 직사각형이 걸치는 **모든 격자**가 그 수평면에서 관측됐는지 검사한다. 가려진 내부 구멍을 메우지 않는다. 후보 좌표는 발바닥 외접 직사각형의 중심이다. 실제 로봇에 적용할 때는 해당 발과 장착물의 외곽, 보정 오차와 착지 오차를 직접 확인한다. [IEEE Humanoids 논문](https://arxiv.org/abs/1907.08673) · [IHMC 저자들의 발바닥·평면 교차 코드](https://github.com/ihmcrobotics/ihmc-open-robotics-software/blob/4ffac8d49f68425ff89324b2e7402a0e5c9b8d91/ihmc-footstep-planning/src/main/java/us/ihmc/footstepPlanning/graphSearch/footstepSnapping/FootstepNodeSnappingTools.java#L28-L48) · [Unitree G1 공식 모델](https://github.com/unitreerobotics/unitree_ros/tree/157ff950351e5f535e03c5d85a16b7d594b3dbcc/robots/g1_description)

**컨테이너 내부 · 위에서 측정한 기록으로 후보 조회**

```bash
read -rp '발 외곽 길이(m)와 폭(m): ' FOOT_L FOOT_W
read -rp '발 방향(도)과 방향 오차(도): ' YAW YAW_ERR
read -rp '가장자리 여유(m)와 위치 오차(m): ' EDGE_MARGIN XY_ERR
g1 stairs assess --run "$RUN_ID" --foot-length-m "$FOOT_L" --foot-width-m "$FOOT_W" \
  --yaw-deg "$YAW" --yaw-uncertainty-deg "$YAW_ERR" \
  --edge-margin-m "$EDGE_MARGIN" --position-uncertainty-m "$XY_ERR"
```

기본은 첫 측정 프레임에서 관측 셀 중심들을 검사한다. 특정 프레임은 `--frame-number N`, 원하는 발 중심은 `--candidate-xy X Y`로 지정한다. 좌표는 측정 때의 중력 좌표계, 발 방향은 +x에서 +y 쪽으로 잰 각도다. 결과는 JSON으로 표준 출력에 나온다. 도달까지 검사할 경우 같은 프레임에서 구한 지지발 중심·방향 `--stance-pose X Y Z YAW_DEG`와 `--max-rise-m`, `--max-drop-m`, `--max-horizontal-reach-m`, `--max-yaw-change-deg`, `--height-uncertainty-m`을 함께 지정한다. 도달 한계에는 현재 구성과 보행 제어기에서 검증한 값을 쓴다.

| 결과 | 의미 |
| --- | --- |
| `support_observed` | 입력한 발 전체와 여유가 관측 격자에 들어간다. |
| `support_and_reach_within_envelope` | 해당 후보에서 지지와 입력한 거리·승강·회전 조건을 모두 통과했다. |
| `outside_measured_envelope`, `outside_reach_envelope` | 입력한 발 또는 후보가 관측된 경계나 지정한 도달 한계를 벗어났다. |
| `unknown` | 측정 근거나 후보 영역의 관측이 부족하다. |

`flight_membership`은 후보 면이 관측한 연속 계단에 속하는지 표시한다. 먼 쪽 경계가 보이지 않아도 발 주변 한 셀 너비까지 연속으로 관측되면 그 내부에서 지지를 평가한다. 격자보다 작은 구멍, 재질의 강도와 마찰을 깊이값만으로 확인할 수는 없다.

단차 15 cm, 경계 간격 35 cm인 합성 4단 계단을 기록 파일에서 재생했을 때 중앙값은 각각 14.99 cm와 34.98 cm였다. 완전히 결측인 깊이 프레임에서는 계단과 지지 후보가 모두 0개였다. 실계단 치수 정확도는 독립 실측과 대조해야 한다.

`robot_climbability`는 `unknown`이다. 한 발의 후보 판정은 입력한 프레임·자세·격자 해상도에서 유효하다. G1의 실제 연속 등반에는 스윙 중 발끝·정강이 충돌, 역기구학, 지지 전환과 균형 및 고수준 제어기의 수행 가능성을 추가로 검증해야 한다.

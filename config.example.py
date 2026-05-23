LOG_FILE  = "images/save_timeout.log"
STATS_FILE = "images/stats.json"

# 카메라 IP 주소 설정 (실제 카메라 IP로 변경 필요)
SIDE_HOST = "xxx.xxx.xxx.xxx"  # 측면 카메라 IP 주소
TOP_HOST  = "xxx.xxx.xxx.xxx"  # 상단 카메라 IP 주소
TCP_PORT  = 3000

FRAME_COUNT    = 10    # 카메라 수집 프레임 수
MIN_SCORE      = 60    # 최소 유효 스코어
MIN_SCORE_GAP  = 5     # 1위-2위 스코어 최소 격차
MIN_CONFIDENCE = 0.50  # 최소 신뢰도
MAX_STD        = 20    # 표준편차 최대값 (초과 시 판별 실패 처리)
MAX_RETRY      = 3     # 판별 실패 시 재시도 횟수
SOCKET_TIMEOUT = 10.0  # 소켓 응답 대기 시간 (초)

HOLDER_MIN_SCORE  = 55
STREAK_MULTIPLIER = 0.15
STREAK_CAP        = 2.0

BASE_DIR = "images"
import os
import json
import threading
import logging
from datetime import datetime
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer

from config import BASE_DIR, TOP_HOST, SIDE_HOST

logging.getLogger('pyftpdlib').setLevel(logging.WARNING)

cup_info  = {}
file_lock = threading.Lock()

_IP_TO_CAM = {TOP_HOST: 'top', SIDE_HOST: 'side'}
# [변경] FTP 저장 방식 전면 변경
# 이전: save_event 단일 threading.Event로 측면/상단 순차 제어
# 현재: _pending + _cam_ready 딕셔너리로 측면/상단 각각 독립 관리
#       카메라별로 이미지를 독립적으로 수신/저장 가능
_pending   = {'top': None, 'side': None}
_cam_ready = {'top': threading.Event(), 'side': threading.Event()}


class CustomFTPHandler(FTPHandler): #ftp/ 1개만 저장이요!
    def log(self, msg, *args, **kwargs):     pass
    def logline(self, msg, *args, **kwargs): pass

    def on_file_received(self, file):
        # [변경] FTP 수신 시 디버깅용 로그 출력 추가
        # 이전: 없음
        # 현재: 수신된 파일명과 접속 IP 출력
        print(f"  [FTP] 수신: ip={self.remote_ip}  파일={os.path.basename(file)}")
        with file_lock:
            actual_cam = _IP_TO_CAM.get(self.remote_ip) # ftp 접속 ip로 실제 케마라 판별
            if actual_cam is None:
                # [변경] 알 수 없는 IP 처리 방식 변경
                # 이전: 로그 없이 그냥 파일 삭제
                # 현재: 등록된 IP 목록 출력 후 삭제 (디버깅 편의)
                print(f"  [FTP] 알 수 없는 IP → 삭제. 등록된 IP: {list(_IP_TO_CAM.keys())}")
                try: os.remove(file)
                except OSError: pass
                return
            old = _pending.get(actual_cam)
            if old and os.path.exists(old):
                try: os.remove(old)
                except OSError: pass
            _pending[actual_cam] = file
        _cam_ready[actual_cam].set()


# [변경] 신규 추가 함수
# 이전: save_event.set() + while 루프로 대기하는 방식 (main.py에서 직접 처리)
# 현재: _cam_ready[cam].wait()로 해당 카메라 이미지만 기다렸다가 저장
#       성공 시 True, 타임아웃 시 False 반환
def wait_and_save(cam, timeout=5.0):
    arrived = _cam_ready[cam].wait(timeout=timeout)
    _cam_ready[cam].clear()

    with file_lock:
        file = _pending.pop(cam, None)

    if not arrived or file is None:
        return False

    result_dir = "approved" if cup_info.get("result") == "수납 허용" else "rejected"
    print(f"  [DEBUG] result: '{cup_info.get('result')}' -> {result_dir}")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_id    = f"{cam}_{timestamp}"
    ext        = os.path.splitext(file)[1]
    img_path   = f"{BASE_DIR}/{cam}/{result_dir}/images/{file_id}{ext}"

    try:
        os.rename(file, img_path)
    except OSError as e:
        print(f"파일 이동 오류: {e}")
        img_path = file

    meta = {
        "file_id":          file_id,
        "image_file":       f"{file_id}{ext}",
        "barcode_data":     cup_info.get("barcode_data", ""),
        "cup_type":         cup_info.get("cup_type", ""),
        "cup_type_score":   cup_info.get("cup_type_score", 0),
        "lid":              cup_info.get("lid", ""),
        "lid_score":        cup_info.get("lid_score", 0),
        "holder":           cup_info.get("holder", ""),
        "holder_score":     cup_info.get("holder_score", 0),
        "foreign_material": cup_info.get("foreign_material", ""),
        "foreign_score":    cup_info.get("foreign_score", 0),
        # [변경] 이물질 세부 정보 필드 추가
        # 이전: 없음
        # 현재: drink/drink_score/trash/trash_score/ice/ice_score 추가
        "drink":            cup_info.get("drink", ""),
        "drink_score":      cup_info.get("drink_score", 0),
        "trash":            cup_info.get("trash", ""),
        "trash_score":      cup_info.get("trash_score", 0),
        "ice":              cup_info.get("ice", ""),
        "ice_score":        cup_info.get("ice_score", 0),
        "result":           cup_info.get("result", ""),
        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #"result" : cup_info.get("result",""),
        "elapsed_sec":      cup_info.get("elapsed_sec", 0),
    }
    label_path = f"{BASE_DIR}/{cam}/{result_dir}/labels/{file_id}.json"
    try:
        with open(label_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"라벨 저장 오류: {e}")
        return False
    print(f"\n저장 완료!")
    print(f"  이미지: {img_path}")
    print(f"  라벨:   {label_path}")
    return True


# [변경] 신규 추가 함수
# 이전: 없음
# 현재: 판별 시작 전 이전 컵의 잔여 이미지 및 Event 상태 초기화
def clear_pending():
    for cam in ('top', 'side'):
        _cam_ready[cam].clear()
        with file_lock:
            old = _pending.pop(cam, None)
            if old and os.path.exists(old):
                try: os.remove(old)
                except OSError: pass


def start_ftp_server():
    authorizer = DummyAuthorizer()
    authorizer.add_user("admin", "1234", BASE_DIR + "/", perm="elradfmwMT")
    handler = CustomFTPHandler
    handler.authorizer = authorizer
    FTPServer(("0.0.0.0", 2121), handler).serve_forever()

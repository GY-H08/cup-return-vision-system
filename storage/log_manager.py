import json
from datetime import datetime

from config import LOG_FILE


def log_save_timeout(camera, cup_info_snapshot): # 저장 실패시 추적용
    """
    ftp 이미지 저장 타임아웃 발생시 로그 파일 기록!
    파라미터: camera: (str) 카메라 종류("side" or "top")
    cuo_info_snapshot (dict): 타임아웃 시점의 cup_info 복사본
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp":    timestamp,
        "camera":camera,
        "barcode_data":cup_info_snapshot.get("barcode_data", ""),
        "result": cup_info_snapshot.get("result", ""),
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[로그] FTP 저장 실패 기록됨: {timestamp}")

import socket
import time
import os
import json
import threading
import logging
import numpy as np
from collections import defaultdict
from datetime import datetime
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from pyftpdlib.authorizers import DummyAuthorizer

logging.getLogger('pyftpdlib').setLevel(logging.WARNING)

LOG_FILE = "images/save_timeout.log"
STATS_FILE = "images/stats.json"

def load_stats():
    
    """
    stats.json에서 통계 데이터 로드.
    파일 없거나 날짜 다르면 오늘 날짜로 초기화된 새 통계 반환.
    
    Returns:
        dict: 통계 데이터. 키: date, total, approved, rejected    
    """

    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(STATS_FILE):
        return{'date':today,'total': 0 , 'approved' : 0 ,'rejected' : 0}
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("date") != today :
        return{'date' : today, 'total': 0, 'approved': 0,'rejected' : 0}
    
    return data

def save_stats(stats):
    """
    현재 통계 데이터를 stats.json에 저장.
    
    Parameters:
        stats (dict): 저장할 통계 데이터. 키: date, total, approved, rejected    
    """
    with open(STATS_FILE,"w", encoding="utf-8") as f:
        json.dump(stats,f, ensure_ascii=False, indent= 2)




SIDE_HOST = "169.254.151.46"
TOP_HOST= "169.254.115.45"
TCP_PORT = 3000

FRAME_COUNT = 10 #카메라 수집 프레임 수
MIN_SCORE  = 60 # 최소 유효 스코어인데 첫 값음 70이였음.. 근데 결과가 좋지 못함. 현재 60으로 하는 중
MIN_SCORE_GAP  = 5 # 1위 결과와 2위 결과의 차이가 최소 5는 나야함
MIN_CONFIDENCE = 0.50
MAX_STD = 20 #결과값의 표준편차 최대값임. 이거보다 크면 그냥 판별 실패 처리
MAX_RETRY = 3 # 판별 실패시 재시도 횟수
SOCKET_TIMEOUT = 10.0 # 데이터 올때까지 기다리는 시간

BASE_DIR = "images" #폴더 생성 중
for folder in ["side", "top"]:
    for result in ["approved", "rejected"]:
        os.makedirs(f"{BASE_DIR}/{folder}/{result}/images", exist_ok=True)
        os.makedirs(f"{BASE_DIR}/{folder}/{result}/labels",  exist_ok=True)

save_event = threading.Event()
cup_info = {}
file_lock = threading.Lock()


class CustomFTPHandler(FTPHandler): #ftp/ 1개만 저장이요!
    def log(self, msg, *args, **kwargs):     pass
    def logline(self, msg, *args, **kwargs): pass

    def on_file_received(self, file):
        with file_lock:
            if not save_event.is_set():
                try: os.remove(file)
                except OSError: pass
                return
            save_event.clear()

            cam  = cup_info.get("camera", "top")
            result_dir = "approved" if cup_info.get("result") == "수납 허용" else "rejected"
            print(f"  [DEBUG] result: '{cup_info.get('result')}' -> {result_dir}")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_id = f"{cam}_{timestamp}"
            ext = os.path.splitext(file)[1]
            img_path = f"{BASE_DIR}/{cam}/{result_dir}/images/{file_id}{ext}"

            try:
                os.rename(file, img_path)
            except OSError as e:
                print(f"파일 이동 오류: {e}")
                img_path = file

            meta = {
                "file_id": file_id,
                "image_file": f"{file_id}{ext}",
                "barcode_data": cup_info.get("barcode_data", ""),
                "cup_type": cup_info.get("cup_type", ""),
                "cup_type_score":cup_info.get("cup_type_score", 0),
                "lid": cup_info.get("lid", ""),
                "lid_score": cup_info.get("lid_score", 0),
                "holder": cup_info.get("holder", ""),
                "holder_score": cup_info.get("holder_score", 0),
                "foreign_material": cup_info.get("foreign_material", ""),
                "foreign_score": cup_info.get("foreign_score", 0),
                "result": cup_info.get("result", ""),
                "timestamp":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                #"result" : cup_info.get("result",""),
                "elapsed_sec": cup_info.get("elapsed_sec",0),

            }
            label_path = f"{BASE_DIR}/{cam}/{result_dir}/labels/{file_id}.json"
            try:
                with open(label_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except OSError as e:
                print(f"라벨 저장 오류: {e}")
                return
            print(f"\n저장 완료!")
            print(f"  이미지: {img_path}")
            print(f"  라벨:   {label_path}")


def log_save_timeout(camera, cup_info_snapshot): # 저장 실패시 추적용
    """
    ftp 이미지 저장 타임아웃 발생시 로그 파일 기록!
    파라미터: camera: (str) 카메라 종류("side" or "top")
    cuo_info_snapshot (dict): 타임아웃 시점의 cup_info 복사본
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp": timestamp,
        "camera":camera,
        "barcode_data":cup_info_snapshot.get("barcode_data", ""),
        "result": cup_info_snapshot.get("result", ""),
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[로그] FTP 저장 실패 기록됨: {timestamp}")


def start_ftp_server():
    authorizer = DummyAuthorizer()
    authorizer.add_user("admin", "1234", BASE_DIR + "/", perm="elradfmwMT")
    handler = CustomFTPHandler
    handler.authorizer = authorizer
    FTPServer(("0.0.0.0", 2121), handler).serve_forever()


threading.Thread(target=start_ftp_server, daemon=True).start()
print("FTP 서버 시작!")
time.sleep(2)


def make_socket(host, port, max_retry=5, retry_delay=3.0): #tcp 연결
    """
    tcp 소켓 생성 및 카메라 연결 실패 시 재시도
    파라미터: 
    host : (str) 카메라 ip 주소
    port (int) tcp 포트 번호
    max_ retry: (int) 최대 재시도 횟수 (기본값 5)
    retry_delay(float):재시도 간격 초 (기본값 3.0)  
    returns: socket.socket: 연결된 소켓 객체
    raises: RuntimeErrorL max_retry 횟수 초과 시
    """
    for attempt in range(1, max_retry + 1):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, port))
            print(f"카메라 연결 성공: {host}:{port}")
            return s
        except OSError as e:
            print(f"연결 실패 ({attempt}/{max_retry}): {e}")
            if attempt < max_retry:
                time.sleep(retry_delay)
    raise RuntimeError(f"카메라 연결 불가: {host}:{port}")


def reconnect_socket(host, port, sock_name="카메라"): #tcp연결 실패했을 시 재시도 함수
    """
      소켓 연결 끊김 시 재연결 시도.
      파라미터:
       host (str): 카메라 IP 주소
        port (int): TCP 포트 번호
        sock_name (str): 로그 출력용 카메라 이름 (기본값 "카메라")

    returns:
    socket.socket: 재연결된 소켓 객체
    None: 재연결 실패 시
      """
    print(f"\n[재연결 시도] {sock_name} ({host}:{port})")
    try:
        return make_socket(host, port)
    except RuntimeError as e:
        print(f"[재연결 실패] {e}")
        return None


sock_side = make_socket(SIDE_HOST, TCP_PORT)
sock_top  = make_socket(TOP_HOST,  TCP_PORT)
print(f"측면 카메라 연결: {SIDE_HOST}:{TCP_PORT}")
print(f"상단 카메라 연결: {TOP_HOST}:{TCP_PORT}")

#stats = {'total': 0, 'approved': 0, 'rejected': 0}
stats = load_stats()

def send_cmd(sock, cmd, delay=0.3):
    """
    카메라에 TCP 명령 전송. ("start" / "stop")
    
    파라미터:
        sock (socket.socket): 명령을 보낼 소켓
        cmd (str): 전송할 명령 문자열
        delay (float): 명령 전송 후 대기 시간 초 (기본값 0.3)
    """
    sock.send(cmd.encode('utf-8'))
    time.sleep(delay)


def flush_socket(sock): # 쌓인 데이터 비우기. 안전장치임. (소켓 버퍼 비우기)
    """수신 버퍼 비우기
    소켓 수신 버퍼에 쌓인 이전 데이터 제거
    프레임 수집 전 반드시 호출하여 이전 컵 데이터 혼입 방지
    파라미터:
    sock (socket.socket): 버퍼를 비울 소켓"""
    sock.setblocking(False)
    try:
        while True:
            sock.recv(4096)
    except (BlockingIOError, OSError):
        pass
    finally:
        sock.setblocking(True)


def parse_side(raw_data): # tcp 데이터 파싱 받기. (측면 카메라)
    """
    측면 카메라 tcp  수신 데이터 파싱.
    포맷 : #바코드 state, 바코드 data, 뚜껑라벨, 뚜껑스코어, 홀더라벨, 홀더스코어@

    파라미터:
    raw_data(bytes): 소켓에서 수신한 원시 바이트 데이터
    returns: 
    list[dict] : 파싱된 프레임 리스트. 각 dict 는 아래 키 포함:
        barcode_state (str): 바코드 인식 성공 여부 ("1" = 성공)
        barcode_data (str): 인식된 바코드 값
        lid_label (str): 뚜껑 라벨 ("뚜껑 있음" / "뚜껑 없음")
        lid_score (int): 뚜껑 판별 스코어
        holder_label (str): 홀더 라벨 ("컵 홀더 있음" / "컵 홀더 없음")
        holder_score (int): 홀더 판별 스코어

    """
    results = []
    try:
        raw_str = raw_data.decode('utf-8', errors='replace')
    except Exception:
        return results

    for frame in raw_str.split('@'):
        frame = frame.strip()
        if '#' not in frame:
            continue
        frame = frame.replace('#', '').strip()
        parts = [p.strip() for p in frame.split(',')]
        if len(parts) < 6:
            continue
        try:
            lid_score = int(parts[3])
            holder_score = int(parts[5])
        except ValueError:
            continue
        results.append({
            'barcode_state':parts[0],
            'barcode_data': parts[1],
            'lid_label': parts[2],
            'lid_score': lid_score,
            'holder_label': parts[4],
            'holder_score': holder_score,
        })
    return results


def parse_top(raw_data):  # tcp 데이터 파싱 받기. (상단 카메라)
    """
    상단 카메라 tcp 수신 데이터 파싱.
    포맷: #001라벨,001스코어,002라벨,002스코어,...,005라벨,005스코어@
    파라미터:
    raw_data (bytes): 소켓에서 수신한 원시 바이트 데이터

    returns:
     list[dict]: 파싱된 프레임 리스트. 각 dict는 아래 키 포함:
        label_001, score_001: 컵 대분류 (종이컵 / 플라스틱 컵)
        label_002, score_002: 종이컵 이물질 유무
        label_003, score_003: 플라스틱 소분류 (투명 / 로고)
        label_004, score_004: 투명컵 이물질 유무
        label_005, score_005: 로고컵 이물질 유무
    """
    results = []
    try:
        raw_str = raw_data.decode('utf-8', errors='replace')
    except Exception:
        return results

    for frame in raw_str.split('@'):
        frame = frame.strip()
        if '#' not in frame:
            continue
        frame = frame.replace('#', '').strip()
        parts = [p.strip() for p in frame.split(',')]
        if len(parts) < 10:
            continue
        try:
            scores = [int(parts[i]) for i in [1, 3, 5, 7, 9]]
        except ValueError:
            continue
        results.append({
            'label_001': parts[0], 'score_001': scores[0],
            'label_002': parts[2], 'score_002': scores[1],
            'label_003': parts[4], 'score_003': scores[2],
            'label_004': parts[6], 'score_004': scores[3],
            'label_005': parts[8], 'score_005': scores[4],
        })
    return results


def collect_frames(sock, parser, label_fn, name="카메라"):

    """
    카메라에서 FRAME_COUNT개 프레임 수집
    타임 아웃 또는 oserror 발생 시 재연결 시도 후 중단
    파라미터:
        sock (socket.socket): 데이터를 수신할 소켓
        parser (callable): 수신 데이터 파싱 함수 (parse_side 또는 parse_top)
        label_fn (callable): 프레임 dict를 로그 문자열로 변환하는 함수
        name (str): 로그 출력용 카메라 이름 (기본값 "카메라")
    returns:
    list[dict]: 수집된 프레임 리스트 (REANE_COUNT개 미만일 수 있음)
    """
    global sock_side, sock_top

    results = []
    flush_socket(sock)
    sock.settimeout(SOCKET_TIMEOUT)
    print(f"\n{name} - {FRAME_COUNT}프레임 수집 시작...")

    while len(results) < FRAME_COUNT:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            print(f"  [경고] 타임아웃. {len(results)}프레임 수집됨.")
            break
        except OSError as e:
            print(f"[오류] {e}")
            if sock is sock_side:
                sock_side = reconnect_socket(SIDE_HOST, TCP_PORT, "측면 카메라")
                if sock_side is None:
                    break
                sock = sock_side
            elif sock is sock_top:
                sock_top = reconnect_socket(TOP_HOST, TCP_PORT, "상단 카메라")
                if sock_top is None:
                    break
                sock = sock_top
            break

        if data:
            for r in parser(data):
                if len(results) < FRAME_COUNT:
                    results.append(r)
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"  [{ts}] [{len(results)}/{FRAME_COUNT}] {label_fn(r)}")

    sock.settimeout(None)
    return results


def side_label(r):
    return (f"바코드:{r['barcode_state']}|{r['barcode_data']}  "
            f"뚜껑:{r['lid_label']}({r['lid_score']})  "
            f"홀더:{r['holder_label']}({r['holder_score']})")


def top_label(r):
    
    return (f"001:{r['label_001']}({r['score_001']})  "
            f"002:{r['label_002']}({r['score_002']})  "
            f"003:{r['label_003']}({r['score_003']})  "
            f"004:{r['label_004']}({r['score_004']})  "
            f"005:{r['label_005']}({r['score_005']})")


HOLDER_MIN_SCORE  = 55
STREAK_MULTIPLIER = 0.15
STREAK_CAP = 2.0


def vote(frames, score_key, label_key, tag="", min_score_override=None): #판별 함수 받은 10개 데이터로 가중 투표 
    """
    수집된 프레임에서 가중 투표로 최종 라벨 결정.
    MIN_SCORE 미만 프레임 제외 시킴, 연속 동일 라벨 가중치 누적해줌
    신뢰도/갭/ 표준편차 조건 미달 시 판별 실패 반환

    파라미터:
    frames (list[dict]): collect_frames로 수집한 프레임 리스트
        score_key (str): 스코어 필드명 (예: "lid_score")
        label_key (str): 라벨 필드명 (예: "lid_label")
        tag (str): 로그 출력용 식별자 (예: "뚜껑", "홀더")
        min_score_override (int|None): 기본 MIN_SCORE 대신 사용할 임계값.
                                       None이면 전역 MIN_SCORE 사용.

     Returns:
        tuple:
            winner (str|None): 최다 득표 라벨. 조건 미달 시 None.
            avg_score (float): 승자 라벨의 평균 스코어. 실패 시 0.
            confidence (float): 승자 라벨의 득표 신뢰도 (0~1). 실패 시 0.

    """
    threshold = min_score_override if min_score_override is not None else MIN_SCORE
    valid = [(r[label_key], r[score_key]) for r in frames if r[score_key] >= threshold]
    if len(valid) < FRAME_COUNT // 2:
        print(f"  [{tag}] 유효 프레임 부족 ({len(valid)}/{FRAME_COUNT})")
        return None, 0, 0

    label_scores  = defaultdict(list)
    for label, score in valid:
        label_scores[label].append(score)

    label_weights = defaultdict(float)
    streak     = 1
    prev_label = None
    for r in frames:
        score = r[score_key]
        label = r[label_key]
        if score < threshold:
            prev_label = None
            streak = 1
            continue
        if label == prev_label:
            streak += 1
        else:
            streak = 1
        multiplier = min(1.0 + (streak - 1) * STREAK_MULTIPLIER, STREAK_CAP)
        label_weights[label] += score * multiplier
        prev_label = label

    sorted_lbs = sorted(label_weights.items(), key=lambda x: x[1], reverse=True)
    winner = sorted_lbs[0][0]
    total_weight = sum(w for _, w in sorted_lbs)
    confidence = label_weights[winner] / total_weight

    winner_scores = label_scores[winner]
    avg_score = sum(winner_scores) / len(winner_scores)
    std_score = float(np.std(winner_scores))

    second_label = sorted_lbs[1][0] if len(sorted_lbs) > 1 else None
    second_avg = (sum(label_scores[second_label]) / len(label_scores[second_label])
                    if second_label else 0)
    score_gap = avg_score - second_avg if second_label else 100

    print(f"  [{tag}] 1위:{winner} 평균:{avg_score:.1f} std:{std_score:.1f} "
          f"신뢰도:{confidence*100:.1f}% 갭:{score_gap:.1f} (임계값:{threshold})")

    if confidence < MIN_CONFIDENCE:
        print(f"  [{tag}] 신뢰도 미달 ({confidence*100:.1f}% < {MIN_CONFIDENCE*100:.0f}%)")
        return None, 0, confidence
    if score_gap < MIN_SCORE_GAP:
        print(f"  [{tag}] 스코어 갭 미달 ({score_gap:.1f} < {MIN_SCORE_GAP})")
        return None, 0, confidence
    if std_score > MAX_STD:
        print(f"  [{tag}] 표준편차 초과 ({std_score:.1f} > {MAX_STD})")
        return None, 0, confidence

    return winner, avg_score, confidence


def vote_barcode(frames): #바코드 데이터는 가중 투표 아니고 그냥 과반 이상으로 뺌
    """
    바코드 인식 성공 여부 및 최다 등장 바코드 데이터 반환
    state ='1' 푸레임이 전체의 과반 이상이어야 성공
    Parameters:
        frames (list[dict]): parse_side로 파싱된 프레임 리스트
    
    Returns:
        tuple:
            - barcode_ok (bool): 바코드 인식 성공 여부
            - barcode_data (str): 가장 많이 인식된 바코드 값. 실패 시 빈 문자열.
    """
    ok_frames = [r for r in frames if r['barcode_state'] == '1']
    if len(ok_frames) < FRAME_COUNT // 2:
        return False, ""
    data_count = defaultdict(int)
    for r in ok_frames:
        data_count[r['barcode_data']] += 1
    best_data = max(data_count, key=data_count.get)
    return True, best_data


def judge_side(): # 3회 재시도. 측면 카메라에서 결과값이 모두 정상으로 출력되어야 결과 반환
    """
     측면 카메라 판별 실행. 최대 MAX_RETRY회 재시도.
    바코드/뚜껑/홀더 모두 성공해야 결과 반환.
    
    Returns:
        dict|None: 판별 성공 시 아래 키 포함 dict 반환. 실패 시 None.
            - barcode_ok (bool): 바코드 인식 성공 여부
            - barcode_data (str): 인식된 바코드 값
            - lid (str): 뚜껑 판별 결과
            - lid_score (float): 뚜껑 평균 스코어
            - holder (str): 홀더 판별 결과
            - holder_score (float): 홀더 평균 스코어   
    """
    for attempt in range(1, MAX_RETRY + 1):
        if attempt > 1:
            print(f"\n[측면] 재시도 {attempt}/{MAX_RETRY}...")
        frames = collect_frames(sock_side, parse_side, side_label, name="측면 카메라")

        barcode_ok, barcode_data = vote_barcode(frames)
        lid,    lid_score,    _ = vote(frames, 'lid_score',    'lid_label',    tag="뚜껑")
        holder, holder_score, _ = vote(frames, 'holder_score', 'holder_label', tag="홀더",
                                       min_score_override=HOLDER_MIN_SCORE)

        if not barcode_ok or lid is None or holder is None:
            continue

        return {
            'barcode_ok': barcode_ok,
            'barcode_data': barcode_data,
            'lid':lid,
            'lid_score': lid_score,
            'holder': holder,
            'holder_score':  holder_score,
        }

    print("[측면] 3회 재시도 후 판별 실패")
    return None


def judge_top():
    """
    상단 카메라 판별 실행 - 트리 구조.
    001(컵 대분류) -> 종이컵: 002(이물질) / 플라스틱: 003(소분류) -> 004 or 005(이물질)
    최대 MAX_RETRY회 재시도.
    
    Returns:
        dict|None: 판별 성공 시 아래 키 포함 dict 반환. 실패 시 None.
            - cup_type (str): 최종 컵 종류 ("종이컵" / "투명 플라스틱 컵" / "로고 플라스틱 컵")
            - cup_type_score (float): 컵 종류 판별 스코어
            - sub_cup_type (str|None): 플라스틱 소분류. 종이컵이면 None.
            - sub_cup_score (float): 소분류 스코어. 종이컵이면 0.
            - foreign (str): 이물질 판별 결과 ("이물질 있음" / "이물질 없음")
            - foreign_score (float): 이물질 판별 스코어
    """
    send_cmd(sock_top, "start", delay=0.5)

    result = None
    for attempt in range(1, MAX_RETRY + 1):
        if attempt > 1:
            print(f"\n[상단] 재시도 {attempt}/{MAX_RETRY}...")
        frames = collect_frames(sock_top, parse_top, top_label, name="상단 카메라")

        cup_main, cup_main_score, _ = vote(frames, 'score_001', 'label_001', tag="001-컵분류")
        if cup_main is None:
            continue

        if cup_main == "종이컵":
            foreign, foreign_score, _ = vote(frames, 'score_002', 'label_002', tag="002-종이컵이물질")
            if foreign is None:
                continue
            result = {
                'cup_type': '종이컵',
                'cup_type_score': cup_main_score,
                'sub_cup_type':  None,
                'sub_cup_score':  0,
                'foreign': foreign,
                'foreign_score': foreign_score,
            }
            print(f"\n[트리] 종이컵 -> 이물질: {foreign} ({foreign_score:.1f}점)")
            break

        elif cup_main == "플라스틱 컵":
            cup_sub, cup_sub_score, _ = vote(frames, 'score_003', 'label_003', tag="003-플라스틱분류")
            if cup_sub is None:
                continue

            if cup_sub == "투명 플라스틱 컵":
                foreign, foreign_score, _ = vote(frames, 'score_004', 'label_004', tag="004-투명컵이물질")
                if foreign is None:
                    continue
                result = {
                    'cup_type': '투명 플라스틱 컵',
                    'cup_type_score': cup_sub_score,
                    'sub_cup_type': cup_sub,
                    'sub_cup_score': cup_sub_score,
                    'foreign':  foreign,
                    'foreign_score': foreign_score,
                }
                print(f"\n[트리] 플라스틱 -> 투명 -> 이물질: {foreign} ({foreign_score:.1f}점)")
                break

            elif cup_sub == "로고 플라스틱 컵":
                foreign, foreign_score, _ = vote(frames, 'score_005', 'label_005', tag="005-로고컵이물질")
                if foreign is None:
                    continue
                result = {
                    'cup_type': '로고 플라스틱 컵',
                    'cup_type_score': cup_sub_score,
                    'sub_cup_type': cup_sub,
                    'sub_cup_score': cup_sub_score,
                    'foreign': foreign,
                    'foreign_score': foreign_score,
                }
                print(f"\n[트리] 플라스틱 -> 로고 -> 이물질: {foreign} ({foreign_score:.1f}점)")
                break

            else:
                print(f"[상단] 유효하지 않은 플라스틱 컵 종류: {cup_sub}")
                continue
        else:
            print(f"[상단] 유효하지 않은 컵 분류: {cup_main}")
            continue

    if result is None:
        print("[상단] 3회 재시도 후 판별 실패")
    return result


print("\n대기 중...\n")

try: #메인 시작  
    #측면 먼저.  측면 이미지 저장 측면 통과 시 상단 판별 후 이미지 저장
    while True:
        cmd = input("\n컵을 넣고 Enter를 눌러주세요...(통계 보기: s + Enter / 통계 초기화: r + Enter)\n")
        if cmd.strip().lower() == 's':
            print("\n========== 통계 ==========")
            print(f"  총 반납 시도:{stats['total']}개")
            print(f"  승인:         {stats['approved']}개")
            print(f"  거부:         {stats['rejected']}개")
            if stats['total'] > 0:
                print(f"  승인율:       {stats['approved'] / stats['total'] * 100:.1f}%")
            print("===========================")
            continue
        elif cmd.strip().lower() == 'r':
            today = datetime.now().strftime("%Y-%m-%d")
            stats['total'] = 0
            stats['approved'] = 0
            stats['rejected'] = 0
            stats['date'] = today
            save_stats(stats)

            print("통계 초기화 완료!")
            continue

        print("\n========== 새 컵 반납 감지 ==========")
        cup_info.clear()
        start_time = time.time()

        print("\n[1단계] 상단 카메라 판별")
        top = judge_top()

        if top is None:
            stats['total']    += 1
            stats['rejected'] += 1
            save_stats(stats)

            print("-> 반납 거부: 상단 판별 실패")
            continue

        print(f"\n[상단 결과]")
        print(f"  컵 종류:  {top['cup_type']} ({top['cup_type_score']:.1f}점)")
        print(f"  이물질:   {top['foreign']} ({top['foreign_score']:.1f}점)")

        top_pass = top['foreign'] == "이물질 없음"

        if not top_pass:
            cup_info.update({
                'cup_type': top['cup_type'],
                'cup_type_score': round(top['cup_type_score'], 1),
                'foreign_material': top['foreign'],
                'foreign_score': round(top['foreign_score'], 1),
                'camera':  'top',
                'result': '반납 거부 - 이물질',
            })
            cup_info['elapsed_sec'] = round(time.time() - start_time, 3)
            stats['total'] += 1
            stats['rejected'] += 1
            save_stats(stats)

            print("\n" + "=" * 50)
            print(" 반납 거부: 이물질 감지")
            print(f"  컵 종류:  {top['cup_type']} ({top['cup_type_score']:.1f}점)")
            print(f"  이물질:   {top['foreign']} ({top['foreign_score']:.1f}점)")
            print("=" * 50)

            save_event.set()
            print("\n사진 저장 대기 중...")
            elapsed = 0
            while save_event.is_set() and elapsed < 5:
                time.sleep(0.5)
                elapsed += 0.5
            if save_event.is_set():
                print("-> 사진 저장 타임아웃")
                save_event.clear()
                log_save_timeout(cup_info.get("camera", "unknown"), dict(cup_info))
            send_cmd(sock_top, "stop", delay=0.3)
            cup_info.clear()
            continue

        print("-> 상단 통과!")
        send_cmd(sock_side, "start", delay=1.0)

        print("\n[2단계] 측면 카메라 판별")
        side = judge_side()

        if side is None:
            stats['total'] += 1
            stats['rejected'] += 1
            save_stats(stats)

            print("-> 반납 거부: 측면 판별 실패")
            send_cmd(sock_top, "stop", delay=0.3)
            send_cmd(sock_side, "stop", delay=0.3)
            continue

        print(f"\n[측면 결과]")
        print(f"  바코드:{'OK - ' + side['barcode_data'] if side['barcode_ok'] else 'FAIL'}")
        print(f"  뚜껑: {side['lid']} ({side['lid_score']:.1f}점)")
        print(f"  홀더: {side['holder']} ({side['holder_score']:.1f}점)")

        side_pass = True

        if not side['barcode_ok']:
            print("-> 반납 거부: 바코드 인식 실패")
            side_pass = False

        if side_pass and side['lid'] == "뚜껑 있음":
            print("-> 반납 거부: 뚜껑, 컵 홀더, 이물질을 제거하고 반납해주세요")
            side_pass = False

        if side_pass and side['holder'] == "컵 홀더 있음":
            print("-> 반납 거부: 뚜껑, 컵 홀더, 이물질을 제거하고 반납해주세요")
            side_pass = False

        if not side_pass:
            cup_info.update({
                'barcode_data': side['barcode_data'],
                'lid':side['lid'],
                'lid_score': round(side['lid_score'], 1),
                'holder':side['holder'],
                'holder_score': round(side['holder_score'], 1),
                'camera':'side',
                'result':  '반납 거부 - 측면',
            })
            cup_info['elapsed_sec'] = round(time.time() - start_time, 3)
            stats['total']    += 1
            stats['rejected'] += 1
            save_stats(stats)

            save_event.set()
            print("\n사진 저장 대기 중...")
            elapsed = 0
            while save_event.is_set() and elapsed < 5:
                time.sleep(0.5)
                elapsed += 0.5
            if save_event.is_set():
                print("-> 사진 저장 타임아웃")
                save_event.clear()
                log_save_timeout(cup_info.get("camera", "unknown"), dict(cup_info))
            send_cmd(sock_top, "stop", delay=0.3)
            send_cmd(sock_side, "stop", delay=0.3)
            cup_info.clear()
            continue

        cup_info.update({
            'barcode_data':     side['barcode_data'],
            'lid':              side['lid'],
            'lid_score':        round(side['lid_score'], 1),
            'holder':           side['holder'],
            'holder_score':     round(side['holder_score'], 1),
            'cup_type':         top['cup_type'],
            'cup_type_score':   round(top['cup_type_score'], 1),
            'foreign_material': top['foreign'],
            'foreign_score':    round(top['foreign_score'], 1),
            'result':           '수납 허용',
        })
        cup_info['elapsed_sec'] = round(time.time() - start_time, 3)
        stats['total']    += 1
        stats['approved'] += 1
        save_stats(stats)

        print("\n" + "=" * 50)
        print(" 반납 허용!")
        print(f"  바코드:{side['barcode_data']}")
        print(f"  뚜껑: {side['lid']} ({side['lid_score']:.1f}점)")
        print(f"  홀더: {side['holder']} ({side['holder_score']:.1f}점)")
        print(f"  컵 종류:{top['cup_type']} ({top['cup_type_score']:.1f}점)")
        print(f"  이물질: {top['foreign']} ({top['foreign_score']:.1f}점)")
        print("=" * 50)

        cup_info['camera'] = 'side'
        save_event.set()
        print("\n사진 저장 대기 중...")
        elapsed = 0
        while save_event.is_set() and elapsed < 5:
            time.sleep(0.5)
            elapsed += 0.5
        if save_event.is_set():
            print("-> 사진 저장 타임아웃")
            save_event.clear()
            log_save_timeout(cup_info.get("camera", "unknown"), dict(cup_info))

        cup_info['camera'] = 'top'
        save_event.set()
        print("\n사진 저장 대기 중...")
        elapsed = 0
        while save_event.is_set() and elapsed < 5:
            time.sleep(0.5)
            elapsed += 0.5
        if save_event.is_set():
            print("-> 사진 저장 타임아웃")
            save_event.clear()
            log_save_timeout(cup_info.get("camera", "unknown"), dict(cup_info))

        send_cmd(sock_top, "stop", delay=0.3)

        cup_info.clear()
        send_cmd(sock_side, "stop", delay=0.3)
        print("\n다음 컵 대기 중...")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\n\n프로그램 종료 중...")
finally:
    try:
        send_cmd(sock_side, "stop", delay=0.3)
        send_cmd(sock_top,  "stop", delay=0.3)
    except Exception:
        pass
    try:
        sock_side.close()
        sock_top.close()
    except Exception:
        pass
    print("카메라 연결 종료. 프로그램 종료.")
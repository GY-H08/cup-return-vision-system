import socket
import time
from datetime import datetime

from config import SIDE_HOST, TOP_HOST, TCP_PORT, SOCKET_TIMEOUT, FRAME_COUNT

sock_side = None
sock_top  = None


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


def init_sockets():
    global sock_side, sock_top
    sock_side = make_socket(SIDE_HOST, TCP_PORT)
    sock_top  = make_socket(TOP_HOST,  TCP_PORT)
    print(f"측면 카메라 연결: {SIDE_HOST}:{TCP_PORT}")
    print(f"상단 카메라 연결: {TOP_HOST}:{TCP_PORT}")

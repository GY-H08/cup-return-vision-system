from core import socket_manager
from core.vote import vote, vote_barcode
from config import MAX_RETRY, HOLDER_MIN_SCORE


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
            'barcode_state': parts[0],
            'barcode_data':  parts[1],
            'lid_label': parts[2],
            'lid_score': lid_score,
            'holder_label': parts[4],
            'holder_score': holder_score,
        })
    return results


def side_label(r):
    return (f"바코드:{r['barcode_state']}|{r['barcode_data']}  "
            f"뚜껑:{r['lid_label']}({r['lid_score']})  "
            f"홀더:{r['holder_label']}({r['holder_score']})")


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
        frames = socket_manager.collect_frames(
            socket_manager.sock_side, parse_side, side_label, name="측면 카메라"
        )

        barcode_ok, barcode_data = vote_barcode(frames)
        lid,    lid_score,    _ = vote(frames, 'lid_score',    'lid_label',    tag="뚜껑")
        holder, holder_score, _ = vote(frames, 'holder_score', 'holder_label', tag="홀더",
                                       min_score_override=HOLDER_MIN_SCORE)

        if not barcode_ok or lid is None or holder is None:
            continue

        return {
            'barcode_ok': barcode_ok,
            'barcode_data': barcode_data,
            'lid': lid,
            'lid_score': lid_score,
            'holder': holder,
            'holder_score':  holder_score,
        }

    print("[측면] 3회 재시도 후 판별 실패")
    return None

from core import socket_manager
from core.vote import vote
from config import MAX_RETRY


# [변경] 신규 추가 함수
# 이전: 없음
# 현재: 004/005/006 판별 시 vote 실패해도 단순 다수결로 fallback하기 위해 추가
def _majority_label(frames, label_key, score_key):
    tally = {}
    for f in frames:
        lb = f.get(label_key)
        if lb:
            tally[lb] = tally.get(lb, 0) + 1
    if not tally:
        return None, 0
    label = max(tally, key=tally.get)
    scores = [f[score_key] for f in frames if f.get(label_key) == label]
    return label, (sum(scores) / len(scores) if scores else 0)


def parse_top(raw_data):  # tcp 데이터 파싱 받기. (상단 카메라)
    """
    상단 카메라 tcp 수신 데이터 파싱.
    포맷: #001라벨,001스코어,002라벨,002스코어,...,005라벨,005스코어@
    파라미터:
    raw_data (bytes): 소켓에서 수신한 원시 바이트 데이터

    returns:
     list[dict]: 파싱된 프레임 리스트. 각 dict는 아래 키 포함:
        label_001, score_001: 컵 대분류 (종이컵 / 플라스틱컵)
        label_002, score_002: 종이컵 이물질 유무
        label_003, score_003: 플라스틱컵 이물질 유무
        label_004, score_004: 음료 유무
        label_005, score_005: 쓰레기 유무
        label_006, score_006: 얼음 유무
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
        # [변경] 상단 카메라 툴 구성 변경으로 필드 수 증가
        # 이전: 필드 10개 (001~005), scores = [int(parts[i]) for i in [1, 3, 5, 7, 9]]
        # 현재: 필드 12개 (001~006), scores = [int(parts[i]) for i in [1, 3, 5, 7, 9, 11]]
        if len(parts) < 12:
            continue
        try:
            scores = [int(parts[i]) for i in [1, 3, 5, 7, 9, 11]]
        except ValueError:
            continue
        results.append({
            'label_001': parts[0],  'score_001': scores[0],
            'label_002': parts[2],  'score_002': scores[1],
            'label_003': parts[4],  'score_003': scores[2],
            'label_004': parts[6],  'score_004': scores[3],
            'label_005': parts[8],  'score_005': scores[4],
            # [변경] 얼음 유무 판별 툴(006) 추가
            # 이전: 없음
            # 현재: label_006, score_006 파싱
            'label_006': parts[10], 'score_006': scores[5],
        })
    return results


def top_label(r):

    return (f"001:{r['label_001']}({r['score_001']})  "
            f"002:{r['label_002']}({r['score_002']})  "
            f"003:{r['label_003']}({r['score_003']})  "
            f"004:{r['label_004']}({r['score_004']})  "
            f"005:{r['label_005']}({r['score_005']})  "
            f"006:{r['label_006']}({r['score_006']})")


def judge_top():
    """
    상단 카메라 판별 실행 - 트리 구조.
    001(컵 대분류) -> 종이컵: 002(이물질 유무)
                   -> 플라스틱컵: 003(이물질 유무)
                                  -> 이물질 없음: 반납 허용
                                  -> 이물질 있음: 004(음료 유무) / 005(쓰레기 유무) / 006(얼음 유무)
                                                  -> 세부 이물질 종류 파악 후 반납 거부
    최대 MAX_RETRY회 재시도.

    Returns:
        dict|None: 판별 성공 시 아래 키 포함 dict 반환. 실패 시 None.
            - cup_type (str): 최종 컵 종류 ("종이컵" / "플라스틱컵")
            - cup_type_score (float): 컵 종류 판별 스코어
            - foreign (str): 이물질 판별 결과 ("이물질 있음" / "이물질 없음")
            - foreign_score (float): 이물질 판별 스코어
            - drink (str|None): 음료 유무 판별 결과. 이물질 없으면 None.
            - drink_score (float|None): 음료 유무 판별 스코어. 이물질 없으면 None.
            - trash (str|None): 쓰레기 유무 판별 결과. 이물질 없으면 None.
            - trash_score (float|None): 쓰레기 유무 판별 스코어. 이물질 없으면 None.
            - ice (str|None): 얼음 유무 판별 결과. 이물질 없으면 None.
            - ice_score (float|None): 얼음 유무 판별 스코어. 이물질 없으면 None.
    """
    socket_manager.send_cmd(socket_manager.sock_top, "start", delay=0.5)

    result = None
    for attempt in range(1, MAX_RETRY + 1):
        if attempt > 1:
            print(f"\n[상단] 재시도 {attempt}/{MAX_RETRY}...")
        frames = socket_manager.collect_frames(
            socket_manager.sock_top, parse_top, top_label, name="상단 카메라"
        )

        cup_main, cup_main_score, _ = vote(frames, 'score_001', 'label_001', tag="001-컵분류")
        if cup_main is None:
            continue

        if cup_main == "종이컵":
            foreign, foreign_score, _ = vote(frames, 'score_002', 'label_002', tag="002-종이컵이물질")
            if foreign is None:
                continue
            result = {
                'cup_type':       '종이컵',
                'cup_type_score': cup_main_score,
                'foreign':        foreign,
                'foreign_score':  foreign_score,
                'drink':          None,
                'drink_score':    None,
                'trash':          None,
                'trash_score':    None,
                'ice':            None,
                'ice_score':      None,
            }
            print(f"\n[트리] 종이컵 -> 이물질: {foreign} ({foreign_score:.1f}점)")
            break

        # [변경] 플라스틱 컵 트리 구조 전면 변경
        # 이전:
        #   001(종이컵 / 플라스틱 컵)
        #     → 종이컵:     002(이물질 있음 / 이물질 없음)
        #     → 플라스틱 컵: 003(투명 플라스틱 컵 / 로고 플라스틱 컵)
        #                    → 투명 플라스틱 컵: 004(이물질 있음 / 이물질 없음)
        #                    → 로고 플라스틱 컵: 005(이물질 있음 / 이물질 없음)
        #
        # 현재:
        #   001(종이컵 / 플라스틱컵)
        #     → 종이컵:    002(이물질 있음 / 이물질 없음)
        #     → 플라스틱컵: 003(이물질 있음 / 이물질 없음)
        #                   → 이물질 없음: 반납 허용
        #                   → 이물질 있음: 004(음료 있음 / 음료 없음)
        #                                  005(쓰레기 있음 / 쓰레기 없음)
        #                                  006(얼음 있음 / 얼음 없음)
        #                                  → 세부 이물질 종류 파악 후 반납 거부
        #
        # 변경 이유: 투명/로고 소분류 제거, 이물질 세부 종류 판별 기능 추가
        # 컵 종류 라벨명도 변경: "플라스틱 컵" → "플라스틱컵" (EasyVS 모델 라벨과 일치)
        elif cup_main == "플라스틱컵":
            foreign, foreign_score, _ = vote(frames, 'score_003', 'label_003', tag="003-플라스틱이물질")
            if foreign is None:
                continue
            # [변경] EasyVS 라벨 오타 자동 보정 추가
            # 이전: 없음
            # 현재: "이믈질" → "이물질" 자동 치환
            foreign = foreign.replace("이믈질", "이물질")

            if foreign == "이물질 없음":
                result = {
                    'cup_type':       '플라스틱컵',
                    'cup_type_score': cup_main_score,
                    'foreign':        foreign,
                    'foreign_score':  foreign_score,
                    'drink':          None,
                    'drink_score':    None,
                    'trash':          None,
                    'trash_score':    None,
                    'ice':            None,
                    'ice_score':      None,
                }
                print(f"\n[트리] 플라스틱 -> 이물질: {foreign} ({foreign_score:.1f}점)")
                break

            elif foreign == "이물질 있음":
                drink, drink_score, _ = vote(frames, 'score_004', 'label_004', tag="004-음료")
                if drink is None:
                    drink, drink_score = _majority_label(frames, 'label_004', 'score_004')
                trash, trash_score, _ = vote(frames, 'score_005', 'label_005', tag="005-쓰레기")
                if trash is None:
                    trash, trash_score = _majority_label(frames, 'label_005', 'score_005')
                ice,   ice_score,   _ = vote(frames, 'score_006', 'label_006', tag="006-얼음")
                if ice is None:
                    ice, ice_score = _majority_label(frames, 'label_006', 'score_006')
                result = {
                    'cup_type':       '플라스틱컵',
                    'cup_type_score': cup_main_score,
                    'foreign':        foreign,
                    'foreign_score':  foreign_score,
                    'drink':          drink,
                    'drink_score':    drink_score,
                    'trash':          trash,
                    'trash_score':    trash_score,
                    'ice':            ice,
                    'ice_score':      ice_score,
                }
                print(f"\n[트리] 플라스틱 -> 이물질 있음 -> 음료:{drink} 쓰레기:{trash} 얼음:{ice}")
                break

            else:
                print(f"[상단] 유효하지 않은 이물질 결과: {foreign}")
                continue
        else:
            print(f"[상단] 유효하지 않은 컵 분류: {cup_main}")
            continue

    if result is None:
        print("[상단] 3회 재시도 후 판별 실패")
    return result

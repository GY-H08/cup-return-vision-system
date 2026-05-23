import numpy as np
from collections import defaultdict

from config import (
    MIN_SCORE, MIN_SCORE_GAP, MIN_CONFIDENCE, MAX_STD,
    FRAME_COUNT, STREAK_MULTIPLIER, STREAK_CAP,
)


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
    score_gap    = avg_score - second_avg if second_label else 100

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

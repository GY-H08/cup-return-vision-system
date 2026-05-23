import time
import threading
from datetime import datetime

import core.socket_manager as socket_manager
# [변경] FTP 저장 방식 변경에 따른 import 변경
# 이전: from core.ftp_handler import save_event, cup_info, start_ftp_server
# 현재: from core.ftp_handler import cup_info, start_ftp_server, wait_and_save, clear_pending
from core.ftp_handler import cup_info, start_ftp_server, wait_and_save, clear_pending
from storage.file_manager import init_directories
from storage.stats_manager import load_stats, save_stats
from storage.log_manager import log_save_timeout
from camera.side_camera import judge_side
from camera.top_camera import judge_top

init_directories()

threading.Thread(target=start_ftp_server, daemon=True).start()
print("FTP 서버 시작!")
time.sleep(2)

socket_manager.init_sockets()

#stats = {'total': 0, 'approved': 0, 'rejected': 0}
stats = load_stats()

print("\n대기 중...\n")


def run_inspection() -> dict:
    """
    컵 반납 판별 1회 실행.

    Returns:
        dict:
            - result (str): "수납 허용" / "반납 거부 - 이물질 감지" / "반납 거부 - 뚜껑 있음" /
                            "반납 거부 - 홀더 있음" / "반납 거부 - 바코드 인식 실패" /
                            "반납 거부 - 상단 판별 실패" / "반납 거부 - 측면 판별 실패"
            - barcode_data (str): 인식된 바코드 값. 인식 실패 시 빈 문자열.
            - cup_type (str): 컵 종류. 판별 안 됐으면 빈 문자열.
            - lid (str): 뚜껑 유무. 판별 안 됐으면 빈 문자열.
            - holder (str): 홀더 유무. 판별 안 됐으면 빈 문자열.
            - foreign_material (str): 이물질 유무. 판별 안 됐으면 빈 문자열.
            - elapsed_sec (float): 판별 소요 시간(초). 판별 못 했으면 0.0.
    """
    print("\n========== 새 컵 반납 감지 ==========")
    cup_info.clear()
    # [변경] 판별 시작 전 이전 컵 잔여 이미지 제거
    # 이전: 없음
    # 현재: clear_pending() 호출로 _pending/_cam_ready 초기화
    clear_pending()
    start_time = time.time()

    # [변경] 판별 흐름 전면 변경
    # 이전: 상단 통과해야만 측면으로 넘어가는 순차 구조, 중간 거부 시 즉시 return
    # 현재: 상단/측면 무조건 둘 다 실행 후 최종 판정 합산
    # 변경 이유: 하드웨어 구조상 뚜껑 있는 컵이 들어오면 상단이 판별 실패하여
    #            측면까지 못 가는 문제 발생 → 측면에서 뚜껑 거부 처리 불가 문제 해결
    print("\n[1단계] 상단 카메라 판별")
    top = judge_top()

    print(f"\n[상단 결과]")
    if top is None:
        print("  판별 실패")
        top_temp_result = '반납 거부 - 판별 실패'
    else:
        print(f"  컵 종류:  {top['cup_type']} ({top['cup_type_score']:.1f}점)")
        print(f"  이물질:   {top['foreign']} ({top['foreign_score']:.1f}점)")
        top_temp_result = '반납 거부 - 이물질' if top['foreign'] == "이물질 있음" else '수납 허용'

    cup_info.update({
        'cup_type':         top['cup_type']                 if top else '',
        'cup_type_score':   round(top['cup_type_score'], 1) if top else 0,
        'foreign_material': top['foreign']                  if top else '',
        'foreign_score':    round(top['foreign_score'], 1)  if top else 0,
        'drink':            top.get('drink')                if top else None,
        'drink_score':      top.get('drink_score')          if top else None,
        'trash':            top.get('trash')                if top else None,
        'trash_score':      top.get('trash_score')          if top else None,
        'ice':              top.get('ice')                  if top else None,
        'ice_score':        top.get('ice_score')            if top else None,
        'camera':           'top',
        'result':           top_temp_result,
    })
    cup_info['elapsed_sec'] = round(time.time() - start_time, 3)

    # [변경] FTP 저장 방식 변경
    # 이전: save_event.set() + while 루프로 직접 대기
    # 현재: wait_and_save(cam) 호출로 처리, 타임아웃 시 False 반환
    print("\n상단 사진 저장 대기 중...")
    if not wait_and_save('top'):
        print("-> 사진 저장 타임아웃")
        log_save_timeout('top', dict(cup_info))
    socket_manager.send_cmd(socket_manager.sock_top, "stop", delay=0.3)

    print("\n[2단계] 측면 카메라 판별")
    socket_manager.send_cmd(socket_manager.sock_side, "start", delay=1.0)
    side = judge_side()

    if side is not None:
        print(f"\n[측면 결과]")
        print(f"  바코드:{'OK - ' + side['barcode_data'] if side['barcode_ok'] else 'FAIL'}")
        print(f"  뚜껑: {side['lid']} ({side['lid_score']:.1f}점)")
        print(f"  홀더: {side['holder']} ({side['holder_score']:.1f}점)")
    else:
        print("  판별 실패")

    # [변경] 거부 사유 처리 방식 변경
    # 이전: 거부 조건마다 즉시 return
    # 현재: specific 리스트로 거부 사유 수집 후 최종 판정에서 한 번에 처리
    specific = []
    if top is not None and top['foreign'] == "이물질 있음":
        specific.append("이물질 감지")
    if side is not None:
        # [변경] 뚜껑 거부 조건 라벨명 변경
        # 이전: side['lid'] == "뚜껑 있음"
        # 현재: side['lid'] == "컵 뚜껑 있음" (EasyVS 모델 라벨과 일치시킴)
        if side['lid'] == "컵 뚜껑 있음":
            specific.append("뚜껑 있음")
        if side['holder'] == "컵 홀더 있음":
            specific.append("홀더 있음")
        if not side['barcode_ok']:
            specific.append("바코드 인식 실패")

    if specific:
        reject_reason = specific[0]
    elif top is None:
        reject_reason = "상단 판별 실패"
    elif side is None:
        reject_reason = "측면 판별 실패"
    else:
        reject_reason = None

    final_result = '수납 허용' if reject_reason is None else f'반납 거부 - {reject_reason}'

    cup_info.update({
        'barcode_data': side['barcode_data'] if side else '',
        'lid':          side['lid']          if side else '',
        'lid_score':    round(side['lid_score'], 1)    if side else 0,
        'holder':       side['holder']       if side else '',
        'holder_score': round(side['holder_score'], 1) if side else 0,
        'camera':       'side',
        'result':       final_result,
    })
    cup_info['elapsed_sec'] = round(time.time() - start_time, 3)
    elapsed_sec = cup_info['elapsed_sec']

    socket_manager.send_cmd(socket_manager.sock_side, "stop", delay=0.3)
    print("\n측면 사진 저장 대기 중...")
    if not wait_and_save('side'):
        print("-> 사진 저장 타임아웃")
        log_save_timeout('side', dict(cup_info))

    # [변경] 통계 카운트 위치 변경
    # 이전: 거부/허용 각 분기마다 즉시 카운트
    # 현재: 최종 판정 후 한 번만 카운트
    stats['total'] += 1
    if reject_reason is None:
        stats['approved'] += 1
    else:
        stats['rejected'] += 1
    save_stats(stats)

    print("\n" + "=" * 50)
    if reject_reason is None:
        print(" 반납 허용!")
        print(f"  바코드:{side['barcode_data']}")
        print(f"  뚜껑: {side['lid']} ({side['lid_score']:.1f}점)")
        print(f"  홀더: {side['holder']} ({side['holder_score']:.1f}점)")
        print(f"  컵 종류:{top['cup_type']} ({top['cup_type_score']:.1f}점)")
        print(f"  이물질: {top['foreign']} ({top['foreign_score']:.1f}점)")
    else:
        print(f"-> 반납 거부: {reject_reason}")
    print("=" * 50)

    cup_info.clear()
    print("\n다음 컵 대기 중...")
    time.sleep(0.5)

    return {
        'result':           final_result,
        'barcode_data':     side['barcode_data'] if side else '',
        'cup_type':         top['cup_type']      if top  else '',
        'lid':              side['lid']           if side else '',
        'holder':           side['holder']        if side else '',
        'foreign_material': top['foreign']        if top  else '',
        'elapsed_sec':      elapsed_sec,
    }


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
        else:
            result = run_inspection()

except KeyboardInterrupt:
    print("\n\n프로그램 종료 중...")
finally:
    try:
        socket_manager.send_cmd(socket_manager.sock_side, "stop", delay=0.3)
        socket_manager.send_cmd(socket_manager.sock_top,  "stop", delay=0.3)
    except Exception:
        pass
    try:
        socket_manager.sock_side.close()
        socket_manager.sock_top.close()
    except Exception:
        pass
    print("카메라 연결 종료. 프로그램 종료.")

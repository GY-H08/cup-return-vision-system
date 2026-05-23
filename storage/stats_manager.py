import os
import json
from datetime import datetime

from config import STATS_FILE


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

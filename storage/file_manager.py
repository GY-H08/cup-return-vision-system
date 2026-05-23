import os

from config import BASE_DIR


def init_directories():
    for folder in ["side", "top"]:
        for result in ["approved", "rejected"]:
            os.makedirs(f"{BASE_DIR}/{folder}/{result}/images", exist_ok=True)
            os.makedirs(f"{BASE_DIR}/{folder}/{result}/labels",  exist_ok=True)

# -*- coding: UTF8 -*-
import re
import os
import sys
import cv2
import time
import math
import string
import random
import ffmpeg
import asyncio
import hashlib
import platform
import subprocess
import shlex
import shutil
import ssl
from zlib import crc32
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi.responses import StreamingResponse

from utils.log import log as logger
from config import *

# 2FA
import pyotp
secret_key = 'UTVVO2XNK3PD525OFQUQCQYL5DRU5SOA'

# colorama
from colorama import Fore, Style, init
init(autoreset=True)
red = Fore.LIGHTRED_EX
blue = Fore.LIGHTBLUE_EX
green = Fore.LIGHTGREEN_EX
black = Fore.LIGHTBLACK_EX
magenta = Fore.LIGHTMAGENTA_EX
reset = Style.RESET_ALL

# ------------------------------------------------------

def generate_userid(email):
    input_str = f"{email}{time.time()}"
    hash_val = hashlib.sha256(input_str.encode()).hexdigest()
    randint = int(hash_val[:5], 16)
    userid = str(int(round(time.time() * 590) + randint))
    # print(f"email: {email} => userid: {userid}")
    return userid


def shift_char(char: str, shift: int) -> str:
    """
    对单个字符 char 进行偏移, shift 为偏移量
    """
    if 'A' <= char <= 'Z':
        return chr((ord(char) - ord('A') + shift) % 26 + ord('A'))
    elif 'a' <= char <= 'z':
        return chr((ord(char) - ord('a') + shift) % 26 + ord('a'))
    elif '0' <= char <= '9':
        return chr((ord(char) - ord('0') + shift) % 10 + ord('0'))
    else:
        return chr(ord(char) + shift)

def floor_decimal(n, decimals=0):
    """
    小数向下取整
    """
    multiplier = 10 ** decimals
    return math.floor(n * multiplier) / multiplier

def generate_register_code(userid, length=5):
    # 生成随机码
    src_code = "".join(random.sample(string.ascii_letters + string.digits, length))
    # 生成随机顺序
    input_str = f"{userid}NODEREGISTER{time.time()}"
    hash_val = hashlib.sha256(input_str.encode()).hexdigest()
    sort_code = hash_val[:length]
    # 随机码按序偏移
    referral_result = []
    for char, shift_digit in zip(src_code, sort_code):
        shift = int(shift_digit, 16)  # 将数字字符转为整数
        referral_result.append(shift_char(char, shift))
    register_code = ''.join(referral_result).upper()
    # register_code = "ga" + ''.join(referral_result)
    # logger.debug(f"src_code: {src_code} sort_code: {sort_code} => register_code: {register_code}")
    return register_code


def validate_sfzid(sfzid: str) -> bool:
    """
    验证18位身份证号码的合法性
    
    Args:
        sfzid (str): 身份证号码字符串
        
    Returns:
        bool: 验证结果，True表示合法，False表示不合法
    """
    # 基本格式检查
    if not sfzid or len(sfzid) != 18:
        return False
    
    # 检查是否全部为数字，除了最后一位可能是X
    if not re.match(r'^\d{17}[\dXx]$', sfzid):
        return False
    
    # 各位权重值
    weight_factors = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    
    # 校验码对应值
    check_codes = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']
    
    # 计算前17位与权重的乘积和
    sum_value = 0
    for i in range(17):
        sum_value += int(sfzid[i]) * weight_factors[i]
    
    # 计算校验码
    mod = sum_value % 11
    expected_check_code = check_codes[mod]
    
    # 比较校验码
    return sfzid[17].upper() == expected_check_code

def validate_email(email: str) -> bool:
    """
    验证邮箱地址格式
    
    Args:
        email (str): 邮箱地址字符串
        
    Returns:
        bool: 验证结果，True表示合法，False表示不合法
    """
    if not email:
        return False
    
    # 邮箱正则表达式
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# ------------------------------------------------------

def check_ssl_files(certfile, keyfile):
    if not os.path.exists(certfile):
        certfile = os.path.join(BASE_DIR, certfile)
    if not os.path.exists(keyfile):
        keyfile = os.path.join(BASE_DIR, keyfile)
    if os.path.exists(certfile) and os.path.exists(keyfile):
        try:
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(certfile=SSL_CERTFILE, keyfile=SSL_KEYFILE)
        except ssl.SSLError as e:
            logger.error(f"Failed to load SSL cert or key: {e}")
            certfile=''
            keyfile=''
        except FileNotFoundError as e:
            logger.info(f"SSL cert or key file not found: {e}")
            certfile=''
            keyfile=''
    else:
        certfile=''
        keyfile=''
    return certfile, keyfile

def check_2fa(pwd: str):
    """
    2FA校验
    """
    ## 无效PWD
    if len(pwd) != 6:
        logger.error(f"STATUS: 400 ERROR: Invalid pwd")
        return False

    ## 生成当前的2FA密码
    totp = pyotp.TOTP(secret_key)
    current_password = totp.now()
    logger.info(f"current_password: {green}{current_password} {black}pwd: {green}{pwd}")
    ## 密码校验
    if current_password != pwd:
        logger.error(f"STATUS: 400 ERROR: Password verification failed")
        return False
    logger.success(f"STATUS: 200 INFO: Password verification successful")
    return True

def is_base58_encoded(s):
    """
    检查字符串是否为有效的Base58编码字符串
    
    Base58字符集: 123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
    (去除了容易混淆的字符: 0, O, I, l)
    
    Args:
        s (str): 要检查的字符串
        
    Returns:
        bool: 如果是有效的Base58编码返回True，否则返回False
    """
    if not isinstance(s, str) or len(s) == 0:
        return False
    
    # Base58允许的字符集
    base58_chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    
    # 检查字符串是否只包含Base58字符
    if not all(c in base58_chars for c in s):
        return False
    
    return True

def is_base58_encoded_regex(s):
    """
    使用正则表达式检查字符串是否为有效的Base58编码字符串
    
    Args:
        s (str): 要检查的字符串
        
    Returns:
        bool: 如果是有效的Base58编码返回True，否则返回False
    """
    if not isinstance(s, str) or len(s) == 0:
        return False
    
    # Base58正则表达式模式
    base58_pattern = r'^[1-9A-HJ-NP-Za-km-z]+$'
    
    return bool(re.match(base58_pattern, s))

def get_hostname():
    hostname = platform.node()
    return hostname

# ------------------------------------------------------

def run_command(cmd):
    """
    执行命令
    """
    output = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    #rst = output.stdout.read().decode("UTF8").strip()
    rst = output.stdout.readlines()
    return rst

# ------------------------------------------------------

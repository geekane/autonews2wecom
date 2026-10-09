# -*- coding: utf-8 -*-
"""
a_bogus v1.0.1.20 纯 Python 实现
1:1 翻译自 BililiveRecorder.Avalonia 的 Abogus.cs (C#)
原 C# 来源: github.com/yaobiao131/BililiveRecorder.Avalonia Platform/BililiveRecorder.Douyin/Abogus.cs
配套 webmssdk.js: 同目录 webmssdk.js (485KB, bdms v1.0.1.20 源码)

入口: encrypt(user_agent, query, body) -> a_bogus 字符串
  - query: URL query 串(不含 a_bogus, 不含 pathname)
  - body:  POST body 串(GET 请求传 "")
"""
import random
import time
from gmssl import sm3 as _sm3, func as _func


# ===================== base64 编码表 =====================
TABLE_OBJ = {
    "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
    "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",  # ua
    "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",  # ab
}


# ===================== SM3 (标准国密, 与 C# Sm3 等价) =====================
def _sm3_bytes(data) -> bytes:
    """标准 SM3, 输入 bytes/str, 返回 32 字节 digest"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    hex_str = _sm3.sm3_hash(_func.bytes_to_list(data))
    return bytes.fromhex(hex_str)


def sum_encrypt(data) -> bytes:
    return _sm3_bytes(data)


# ===================== 自定义 base64 (LmStrEncode) =====================
def lm_str_encode(lm_arr, table: str) -> str:
    """整数数组 -> 自定义 base64 字符串 (与 JS/C# 一致, 含余数处理)"""
    assert len(table) == 64
    n = len(lm_arr)
    group_num = n // 3
    out = []
    for i in range(group_num):
        idx = 3 * i
        c1 = lm_arr[idx] & 255
        c2 = lm_arr[idx + 1] & 255 if idx + 1 < n else 0
        c3 = lm_arr[idx + 2] & 255 if idx + 2 < n else 0
        big = (c1 << 16) | (c2 << 8) | c3
        out.append(table[(big & 0xFC0000) >> 18])
        out.append(table[(big & 0x03F000) >> 12])
        out.append(table[(big & 0x000FC0) >> 6])
        out.append(table[big & 0x3F])
    remainder = n % 3
    if remainder == 1:
        idx = group_num * 3
        c1 = lm_arr[idx] & 255
        big = c1 << 16
        out.append(table[(big & 0xFC0000) >> 18])
        out.append(table[(big & 0x03F000) >> 12])
        out.append("==")
    elif remainder == 2:
        idx = group_num * 3
        c1 = lm_arr[idx] & 255
        c2 = lm_arr[idx + 1] & 255
        big = (c1 << 16) | (c2 << 8)
        out.append(table[(big & 0xFC0000) >> 18])
        out.append(table[(big & 0x03F000) >> 12])
        out.append(table[(big & 0x000FC0) >> 6])
        out.append("=")
    return "".join(out)


# ===================== RC4 变种 (Parse) =====================
def parse(lm_str: str, data_str: str) -> str:
    """基于 lm_str 的伪随机变换: S盒[255..0]倒序 + 乘法KSA + 标准PRGA"""
    arr256 = [255 - i for i in range(256)]
    swap_idx = 0
    lm_len = len(lm_str)
    for s in range(256):
        char_code = ord(lm_str[s % lm_len])
        swap_idx = (swap_idx * arr256[s] + swap_idx + char_code) % 256
        arr256[s], arr256[swap_idx] = arr256[swap_idx], arr256[s]

    ret = []
    bak = 0
    for i in range(len(data_str)):
        idx = (i + 1) % 256
        idx2 = (bak + arr256[idx]) % 256
        bak = idx2
        arr256[idx], arr256[idx2] = arr256[idx2], arr256[idx]
        idx3 = (arr256[idx2] + arr256[idx]) % 256
        num = ord(data_str[i]) ^ arr256[idx3]
        ret.append(chr(num))
    return "".join(ret)


def str_to_int_arr(s: str):
    return [ord(c) for c in s]


# ===================== 随机数生成器 =====================
def get_abogus_lm_arr4():
    r1 = random.randint(0, 65535)
    r2 = random.randint(0, 39)
    return [
        (r1 & 170) | 1,
        (r1 & 85) | 2,
        (r2 & 170) | 80,
        (r2 & 85) | 2,
    ]


def get_tm_arr(tm: int):
    tm_num = (tm + 3) & 255
    tm_str = f"{tm_num},"
    return [ord(c) for c in tm_str]


def get_fp_arr():
    # 与 C# 一致的固定指纹串
    fp_str = "1440|266|1440|823|1920|1055|1920|1080|MacIntel"
    return [ord(c) for c in fp_str]


def get_xor_random_arr8():
    r1 = random.randint(0, 65535)
    tmp1 = r1 & 255
    tmp2 = (r1 >> 8) & 255
    r_val = random.randint(0, 255)
    r2 = random.randint(0, 239)
    is_even = r2 + 110
    if is_even % 2 != 0:
        is_even += 1
    return [
        (tmp1 & 170) | 1,
        (tmp1 & 85) | 0,
        (tmp2 & 170) | 0,
        (tmp2 & 85) | 0,
        (is_even & 170) | 1,
        (is_even & 85) | 0,
        (((r_val & 77) | 2 | 16 | 32 | 128) & 170) | 16,
        (((r_val & 77) | 16 | 32 | 128) & 85) | 2,
    ]


# ===================== arr50 重排 (含重复索引, v20 特征) =====================
_NEW_ARR50_INDICES = [
    9, 18, 28, 32, 44, 4, 11, 11, 9, 23,
    12, 37, 24, 39, 3, 22, 35, 11, 5, 42,
    1, 27, 33, 11, 30, 14, 6, 7, 2, 43,
    15, 11, 29, 25, 16, 11, 8, 38, 26, 17,
    9, 11, 11, 0, 31, 7, 46, 47, 48, 49,
]


def get_new_arr50(arr50):
    out = [0] * 50
    for i, idx in enumerate(_NEW_ARR50_INDICES):
        if idx < len(arr50):
            out[i] = arr50[idx]
        else:
            out[i] = 0
    return out


def get_xor_array(arr):
    x = 0
    for v in arr:
        x ^= v
    return [x]


# ===================== 主入口 =====================
def encrypt(user_agent: str, query: str, body: str = "") -> str:
    """
    生成 a_bogus v1.0.1.20
    user_agent: UA 字符串
    query:      URL query 串(不含 a_bogus, 不含 pathname)
    body:       POST body 串(GET 传 "")
    """
    salt = "dhzx"
    current_time = time.time()
    tm1_before = int(current_time * 1000)
    tm2 = tm1_before - 1
    tm1 = int(current_time * 1000)  # 与 tm1_before 同值

    # ---- 三路 SM3 双哈希 ----
    query_arr32 = sum_encrypt(sum_encrypt(f"{query}{salt}"))
    data_arr32 = sum_encrypt(sum_encrypt(f"{body}{salt}"))

    # ---- UA: RC4变种 -> base64(s3) -> SM3 ----
    ua_init = "\x00\x01\x00"
    ua_lm = parse(ua_init, user_agent)
    ua_encoded = lm_str_encode(str_to_int_arr(ua_lm), TABLE_OBJ["s3"])
    ua_arr32 = sum_encrypt(ua_encoded)

    fp_arr = get_fp_arr()

    def _byte_at(arr, i):
        return arr[i] if len(arr) > i else 0

    # ---- 50 元素核心数组 ----
    arr50 = [
        41, 8, 6,
        (tm1 - tm1_before + 3) & 255,

        tm1 & 255,
        (tm1 >> 8) & 255,
        (tm1 >> 16) & 255,
        (tm1 >> 24) & 255,
        (tm1 >> 32) & 255,
        (tm1 >> 40) & 255,

        1, 0,
        129, 0,
        255, 10, 9, 9,
        0, 0, 0, 0,

        # queryArr32 采样 (idx 25,26,27)
        _byte_at(query_arr32, 9),
        _byte_at(query_arr32, 18),
        _byte_at(query_arr32, 3),
        # dataArr32 采样 (idx 28,29,30) ← body 进签名
        _byte_at(data_arr32, 10),
        _byte_at(data_arr32, 19),
        _byte_at(data_arr32, 4),
        # userAgentArr32 采样 (idx 31,32,33)
        _byte_at(ua_arr32, 11),
        _byte_at(ua_arr32, 21),
        _byte_at(ua_arr32, 5),

        # tm2 拆字节 (idx 34-39)
        tm2 & 255,
        (tm2 >> 8) & 255,
        (tm2 >> 16) & 255,
        (tm2 >> 24) & 255,
        (tm2 >> 32) & 255,
        (tm2 >> 40) & 255,

        3,

        # 常量 27092 拆字节 (idx 41-44)
        27092 & 255,
        (27092 >> 8) & 255,
        (27092 >> 16) & 255,
        (27092 >> 24) & 255,

        # 常量 549224 拆字节 (idx 45-48)
        549224 & 255,
        (549224 >> 8) & 255,
        (549224 >> 16) & 255,
        (549224 >> 24) & 255,

        46, 0, 3, 0,  # idx 49,50,51,52
    ]

    new_arr50 = get_new_arr50(arr50)
    xor_random_arr8 = get_xor_random_arr8()
    arr58 = xor_random_arr8 + arr50
    xor_array = get_xor_array(arr58)

    arr4_merge = new_arr50 + fp_arr + get_tm_arr(tm1) + xor_array

    abogus_lm_arr4 = get_abogus_lm_arr4()
    abogus_lm_str = "".join(chr(x) for x in abogus_lm_arr4)

    # ---- 3->4 扩展编码 (注入随机噪声, masks=[145,110,66,189,44,211]) ----
    merge_arr = []
    n = len(arr4_merge)
    # C# : for i < arr4Merge.Length / 3  (int 截断除法)
    group_count = n // 3
    for i in range(group_count):
        idx = 3 * i
        v1 = arr4_merge[idx] if idx < n else 0
        v2 = arr4_merge[idx + 1] if idx + 1 < n else 0
        v3 = arr4_merge[idx + 2] if idx + 2 < n else 0
        r = int(random.random() * 1000) & 255
        merge_arr.append((r & 145) | (v1 & 110))
        merge_arr.append((r & 66) | (v2 & 189))
        merge_arr.append((r & 44) | (v3 & 211))
        merge_arr.append((v1 & 145) | (v2 & 66) | (v3 & 44))

    big_arr = xor_random_arr8 + merge_arr + xor_array
    big_str = "".join(chr(x) for x in big_arr)

    abogus_lm_str += parse("\xd3", big_str)
    abogus_lm_arr = str_to_int_arr(abogus_lm_str)
    result = lm_str_encode(abogus_lm_arr, TABLE_OBJ["s4"])
    return result


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0")
    q = ("device_platform=webapp&aid=6383&channel=channel_pc_web&aweme_id=7682022077243894757"
         "&version_code=170400&version_name=17.4.0&cookie_enabled=true&screen_width=1536"
         "&screen_height=864&browser_language=zh-CN&browser_platform=Win32&browser_name=Edge"
         "&browser_version=154.0.0.0&webid=7687924326851266111")
    b = "aweme_id=7682022077243894757&text=%E4%BD%A0%E5%A5%BD&text_extra=%5B%5D"
    ab = encrypt(ua, q, b)
    print(f"a_bogus len={len(ab)}")
    print(ab)

import datetime
import json
import os
from logger import logger

# 获取当前日期字符串（格式：YYYYMMDD，如20251220）
def get_current_date_str():
    return datetime.datetime.now().strftime("%Y%m%d")

# 获取当前时间字符串（格式：YYYYMMDD_HHMMSS，用于精准标记）
def get_current_datetime_str():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# 接续记录文件路径
RESUME_RECORD_FILE = "alpha_resume_record.json"

# 初始化/加载接续记录
def load_resume_record():
    if os.path.exists(RESUME_RECORD_FILE):
        try:
            with open(RESUME_RECORD_FILE, "r", encoding="utf-8") as f:
                record = json.load(f)
            logger.info(f"成功加载接续记录 | 已处理Alpha数: {len(record.get('processed_alpha_ids', []))}")
            return record
        except Exception as e:
            logger.error(f"加载接续记录失败，将创建新记录: {str(e)}")
    
    # 默认空记录
    return {
        "last_process_time": "",  # 上次处理时间
        "processed_alpha_ids": [],  # 已处理（成功/失败）的Alpha ID列表
        "pending_file_name": "",  # 对应的pending CSV文件名
        "completed_file_name": "",  # 对应的completed CSV文件名
        "failed_file_name": ""  # 对应的failed CSV文件名
    }

# 保存接续记录
def save_resume_record(record):
    try:
        record["last_process_time"] = get_current_datetime_str()
        with open(RESUME_RECORD_FILE, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        logger.debug("成功保存接续记录")
    except Exception as e:
        logger.error(f"保存接续记录失败: {str(e)}")

# 标记Alpha为已处理
def mark_alpha_processed(alpha_id):
    record = load_resume_record()
    if alpha_id not in record["processed_alpha_ids"]:
        record["processed_alpha_ids"].append(alpha_id)
        save_resume_record(record)
    logger.debug(f"标记Alpha {alpha_id} 为已处理")

# 判断Alpha是否已处理
def is_alpha_processed(alpha_id):
    record = load_resume_record()
    return alpha_id in record["processed_alpha_ids"]
# 核心导入：与alpha_generator.py保持一致，兼容原有逻辑
import csv
import json
import os
import yaml
# 恢复原有logger导入，不自行创建日志（避免冲突）
from logger import logger

# 全局加载配置：简洁写法，与你的config.yaml严格对应
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
storage_config = config["storage"]

def init_csv_files():
    """简化初始化：仅创建不存在的CSV文件，保证表头正确"""
    file_paths = [
        storage_config["pending_file"],
        storage_config["completed_file"],
        storage_config["failed_file"]
    ]
    fieldnames = storage_config["fieldnames"]
    
    for file_path in file_paths:
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                logger.info(f"初始化CSV文件成功: {file_path}")
            except Exception as e:
                logger.error(f"初始化CSV文件失败: {file_path} | 错误: {str(e)}")

def read_pending_alphas():
    """
    简化读取逻辑：与alpha_generator.py写入格式兼容，解决转义问题
    """
    pending_file = storage_config["pending_file"]
    alpha_list = []
    fieldnames = storage_config["fieldnames"]
    
    if not os.path.exists(pending_file):
        logger.warning(f"pending表不存在: {pending_file}")
        return []
    
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # 仅简单校验表头，不报错（兼容微小差异）
            if set(reader.fieldnames) != set(fieldnames):
                logger.warning(f"pending表表头不完全匹配，预期: {fieldnames} | 实际: {reader.fieldnames}")
            
            for row in reader:
                # 核心修复：移除regular/expr字段的首尾引号，不做多余反序列化
                row["regular"] = row.get("regular", "").strip('"').strip("'")
                row["expr"] = row.get("expr", "").strip('"').strip("'")
                
                # 仅对settings字段反序列化（与写入逻辑对应）
                try:
                    settings_str = row.get("settings", "{}").strip('"').strip("'")
                    row["settings"] = json.loads(settings_str) if settings_str else {}
                except json.JSONDecodeError:
                    logger.warning(f"settings字段反序列化失败，使用空字典 | Alpha ID: {row.get('alpha_id')}")
                    row["settings"] = {}
                
                # 简单清洗：去除空值，不做多余处理
                for k, v in row.items():
                    row[k] = v.strip() if v and isinstance(v, str) else v
                
                alpha_list.append(row)
        
        logger.info(f"成功读取{len(alpha_list)}个Alpha从pending表: {pending_file}")
        return alpha_list
    
    except Exception as e:
        logger.error(f"读取pending表失败: {str(e)}", exc_info=True)
        return []

def write_alpha_result(alpha_item, status):
    """
    简化写入结果逻辑：与alpha_generator.py写入格式兼容
    """
    if status == "completed":
        target_file = storage_config["completed_file"]
    elif status == "failed":
        target_file = storage_config["failed_file"]
    else:
        logger.warning(f"无效状态: {status}，跳过写入")
        return
    
    fieldnames = storage_config["fieldnames"]
    is_new_file = not os.path.exists(target_file)
    
    try:
        with open(target_file, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if is_new_file:
                writer.writeheader()
            
            # 构建行数据：与alpha_generator.py写入逻辑一致
            row = {}
            for field in fieldnames:
                value = alpha_item.get(field, "")
                if field == "settings" and isinstance(value, dict):
                    row[field] = json.dumps(value, ensure_ascii=False)
                else:
                    row[field] = str(value).strip('"').strip("'")
            
            writer.writerow(row)
        
        logger.info(f"成功写入Alpha结果到{status}表 | ID: {alpha_item.get('alpha_id')}")
    
    except Exception as e:
        logger.error(f"写入{status}表失败 | ID: {alpha_item.get('alpha_id')} | 错误: {str(e)}")

# 兼容原有写入pending表的函数（与alpha_generator.py保持一致）
def write_pending_alphas(alpha_list):
    from alpha_generator import write_pending_alphas as generator_write
    generator_write(alpha_list)

# 其他辅助函数：保持简洁，兼容原有逻辑
def get_current_csv_files():
    return [
        storage_config["pending_file"],
        storage_config["completed_file"],
        storage_config["failed_file"]
    ]

def mark_alpha_processed(alpha_id):
    logger.debug(f"标记Alpha已处理: {alpha_id}")

def is_alpha_processed(alpha_id):
    # 检查已完成表
    completed_file = storage_config["completed_file"]
    if os.path.exists(completed_file):
        with open(completed_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("alpha_id") == alpha_id:
                    return True
    # 检查失败表
    failed_file = storage_config["failed_file"]
    if os.path.exists(failed_file):
        with open(failed_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("alpha_id") == alpha_id:
                    return True
    return False

def load_resume_record():
    return {"processed_alpha_ids": [], "total_processed": 0, "success_count": 0, "fail_count": 0}

def save_resume_record(record):
    logger.debug(f"保存续跑记录: {record}")

# 测试入口：验证读取功能
if __name__ == "__main__":
    init_csv_files()
    # 先运行alpha_generator.py生成pending表，再运行此测试
    pending_alphas = read_pending_alphas()
    for alpha in pending_alphas:
        logger.info(f"读取到Alpha | ID: {alpha.get('alpha_id')} | 表达式: {alpha.get('regular')}")
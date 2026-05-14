import requests
import json
import yaml
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import logger
from auth import refresh_session
from storage import (
    read_pending_alphas,
    write_alpha_result,
    get_current_csv_files
)
from utils import (
    mark_alpha_processed,
    is_alpha_processed,
    load_resume_record,
    save_resume_record
)

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)
auth_config = config["auth"]
sim_config = config["simulation"]
# 新增：最大并发数配置
MAX_WORKERS = config.get("simulation", {}).get("max_workers", 3)

def clean_string(s):
    if not isinstance(s, str):
        return str(s) if s is not None else ""
    return s.strip()

def run_single_alpha(sess, alpha_item):
    alpha_id = clean_string(alpha_item.get("alpha_id", "unknown"))
    
    # 跳过已处理的Alpha
    if is_alpha_processed(alpha_id):
        logger.info(f"跳过已处理的Alpha: {alpha_id}")
        return True, "已处理，无需重复测试", alpha_item
    
    # 提取接口需要的必填字段
    try:
        regular = clean_string(alpha_item.get("regular")) or f"default_regular_{alpha_id}"
    except Exception as e:
        logger.error(f"提取请求字段失败（Alpha ID: {alpha_id}）: {str(e)}")
        mark_alpha_processed(alpha_id)
        return False, "字段提取失败", alpha_item
    
    # 构造请求数据
    request_data = {
        "regular": regular,
        "type": clean_string(alpha_item.get("type", "REGULAR")),
        "settings": alpha_item.get("settings", {})
    }
    
    retry_times = sim_config.get("retry_times", 3)
    for i in range(retry_times):
        try:
            sess = refresh_session(sess)
            headers = {"Content-Type": "application/json"}
            
            # 提交回测请求
            resp = sess.post(
                auth_config["sim_url"],
                json=request_data,
                headers=headers,
                timeout=sim_config.get("timeout", 30)
            )
            
            # 处理429并发限制
            if resp.status_code == 429:
                error_detail = resp.text
                logger.warning(f"Alpha {alpha_id} 触发并发限制（剩余重试: {retry_times-i-1}）: {error_detail}")
                # 等待后重试
                time.sleep(5 * (i + 1))  # 指数退避
                continue
                
            # 处理成功提交的情况（200/201）
            if resp.status_code in [200, 201]:
                # 检查是否有location头用于轮询
                if 'location' in resp.headers:
                    progress_url = resp.headers['location']
                    logger.info(f"Alpha {alpha_id} 已提交，轮询地址: {progress_url}")
                    
                    # 轮询进度
                    while True:
                        progress_resp = sess.get(progress_url, timeout=sim_config.get("timeout", 30))
                        # 检查是否需要重试等待
                        retry_after = float(progress_resp.headers.get("Retry-After", 0))
                        
                        if retry_after > 0:
                            logger.debug(f"Alpha {alpha_id} 等待{retry_after}秒后重试")
                            time.sleep(retry_after)
                        else:
                            # 轮询结束，获取结果
                            result = progress_resp.json()
                            logger.info(f"Alpha {alpha_id} 测试成功 | 结果: {result}")
                            
                            # 新增：提取alpha值并添加到alpha_item中
                            alpha_value = result.get('alpha', '')
                            alpha_item["alpha"] = alpha_value
                            alpha_item["status"] = "completed"
                            alpha_item["error_msg"] = ""
                            mark_alpha_processed(alpha_id)
                            return True, "测试成功", alpha_item
                
                # 没有location头的情况
                response_data = resp.json()
                logger.info(f"Alpha {alpha_id} 测试成功 | 响应: {response_data}")
                
                # 新增：提取alpha值并添加到alpha_item中
                alpha_value = response_data.get('alpha', '')
                alpha_item["alpha"] = alpha_value
                alpha_item["status"] = "completed"
                alpha_item["error_msg"] = ""
                mark_alpha_processed(alpha_id)
                return True, "测试成功", alpha_item
                
            # 处理其他错误状态码
            else:
                error_detail = resp.text
                logger.error(f"Alpha {alpha_id} 请求失败（剩余重试: {retry_times-i-1}）: {resp.status_code} | 详情: {error_detail}")
                if i == retry_times - 1:
                    # 新增：失败时也添加alpha字段，值为空
                    alpha_item["alpha"] = ""
                    alpha_item["status"] = "failed"
                    alpha_item["error_msg"] = error_detail
                    mark_alpha_processed(alpha_id)
                    return False, error_detail, alpha_item
                
        except Exception as e:
            error_detail = str(e)
            logger.error(f"Alpha {alpha_id} 请求异常（剩余重试: {retry_times-i-1}）: {error_detail}")
            if i == retry_times - 1:
                # 新增：失败时也添加alpha字段，值为空
                alpha_item["alpha"] = ""
                alpha_item["status"] = "failed"
                alpha_item["error_msg"] = error_detail
                mark_alpha_processed(alpha_id)
                return False, error_detail, alpha_item
    
    # 新增：重试用尽时也添加alpha字段，值为空
    alpha_item["alpha"] = ""
    mark_alpha_processed(alpha_id)
    return False, "达到最大重试次数", alpha_item

def run_batch_alphas(sess):
    record = load_resume_record()
    processed_count = len(record.get("processed_alpha_ids", []))
    pending_alphas = read_pending_alphas()
    total_unprocessed = len(pending_alphas)
    
    logger.info(f"===== 开始回测（异步并测模式） =====")
    logger.info(f"已处理Alpha数: {processed_count}")
    logger.info(f"待处理Alpha数: {total_unprocessed}")
    logger.info(f"当前使用的CSV文件: {os.path.basename(get_current_csv_files()[0])}")
    logger.info(f"最大并发数: {MAX_WORKERS}")
    
    if not pending_alphas:
        logger.info("无未处理的pending Alpha，回测完成")
        return
    
    success_count = 0
    fail_count = 0
    
    # 使用线程池执行异步任务
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        futures = [executor.submit(run_single_alpha, sess, alpha_item) for alpha_item in pending_alphas]
        
        # 处理完成的任务
        for future in as_completed(futures):
            try:
                success, msg, alpha_item = future.result()
                if success:
                    write_alpha_result(alpha_item, status="completed")
                    success_count += 1
                else:
                    write_alpha_result(alpha_item, status="failed")
                    fail_count += 1
            except Exception as e:
                logger.error(f"处理任务结果异常: {str(e)}")
                fail_count += 1
    
    # 更新记录
    record = load_resume_record()
    record["total_processed"] = len(record.get("processed_alpha_ids", []))
    record["success_count"] = success_count
    record["fail_count"] = fail_count
    save_resume_record(record)
    
    logger.info(f"===== 回测批次完成 =====")
    logger.info(f"本次成功: {success_count} | 本次失败: {fail_count}")
    logger.info(f"累计已处理: {len(record.get('processed_alpha_ids', []))}")
    logger.info(f"剩余待处理: {total_unprocessed - (success_count + fail_count)}")

if __name__ == "__main__":
    from auth import create_auth_session
    sess = create_auth_session()
    run_batch_alphas(sess)
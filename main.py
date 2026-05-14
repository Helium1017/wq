from logger import logger
from auth import create_auth_session
from datafield import get_datafields  # 现在返回多组数据字段字典
from alpha_generator import generate_alpha_list
from storage import init_csv_files, write_pending_alphas
from sim_scheduler import run_batch_alphas

def main():
    try:
        # 1. 初始化存储（保持原有逻辑）
        init_csv_files()
        
        # 2. 创建认证Session（保持原有逻辑）
        sess = create_auth_session()
        
        # 3. 获取数据字段（核心修改：适配多组数据字段）
        # 原逻辑：返回DataFrame → 取单列表；新逻辑：返回字典 {datafield1: [ids...], ...}
        datafield_groups = get_datafields(sess)
        if not datafield_groups:  # 校验多组字段是否为空
            logger.warning("未获取到任何有效数据字段组，程序终止")
            return
        logger.info(f"成功获取 {len(datafield_groups)} 组数据字段：{list(datafield_groups.keys())}")
        
        # 4. 生成Alpha并批量写入pending列表（核心修改：传递多组字段字典）
        alpha_list = generate_alpha_list(datafield_groups)
        if not alpha_list:
            logger.warning("未生成任何Alpha，程序终止")
            return
        write_pending_alphas(alpha_list)
        
        # 5. 批量运行Alpha（异步并测，保持原有逻辑）
        run_batch_alphas(sess)
        
        logger.info("主程序执行完成")
    except Exception as e:
        logger.error(f"主程序执行失败: {str(e)}", exc_info=True)  # 新增exc_info便于调试
        raise

if __name__ == "__main__":
    main()
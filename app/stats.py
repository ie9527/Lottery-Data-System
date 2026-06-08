"""兼容层 - 从拆分后的模块重新导出所有函数"""
# 此文件保持向后兼容，所有功能已拆分到以下模块：
# - query_parser.py:  parse_search_query
# - matcher.py:      SINGLE_DIGIT_TYPES, _fmt, extract_number_string, extract_sorted_string,
#                    wildcard_match, prefix_match, match_list, numbers_contains,
#                    set_subset_match_mode, match_dict
# - stats_service.py: search_by_number, get_history_detail, get_number_appear_detail, advanced_search
# - stats_builder.py: build_number_stats, get_all_number_stats
# - unused.py:        get_unused_numbers

# 重新导出以保持向后兼容
from app.matcher import (
    SINGLE_DIGIT_TYPES, _fmt, extract_number_string, extract_sorted_string,
    wildcard_match, prefix_match, match_list, numbers_contains,
    set_subset_match_mode, match_dict
)
from app.query_parser import parse_search_query
from app.stats_service import search_by_number, get_history_detail, advanced_search
from app.stats_builder import build_number_stats, get_all_number_stats
from app.unused import get_unused_numbers


def get_number_appear_detail(lottery_code, search_text):
    """获取某个号码的详细出现记录（已合并至 stats_service.get_history_detail）"""
    periods, total = get_history_detail(lottery_code, search_text, "group", 1, 9999)
    return periods
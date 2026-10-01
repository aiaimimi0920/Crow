"""
Job Manager - 嗅探任务管理模块

LEGACY NOTICE:
本模块保留为历史 `jobs/*.json` 文件体系的参考实现。
当前运行态主链已经迁移到数据库 `property_search_task` +
`src.collection.seed_service.SeedCollectionService`。
如需把旧 jobs 快照导入数据库，请优先使用：
- `src.collection.search_bootstrap`
- `tools/import_search_jobs_to_db.py`

管理 jobs/ 目录下的任务文件，提供：
1. 扫描所有任务状态
2. 考虑优先城市排序
3. 分配任务给指定session
4. 更新任务进度
"""

import os
import json
import datetime
import threading
import tempfile
from copy import deepcopy
from typing import Optional, Dict, List, Tuple

if __package__:
    from .job_json import format_job_json
else:
    from job_json import format_job_json

# 默认类别和排序参数
DEFAULT_CATEGORIES = ["50025969", "200782003"]  # 住宅用房, 商业用房
DEFAULT_ST_PARAMS = ["2", "1", "0", "3", "4", "5"]  # 排序参数优先级


class JobManager:
    def __init__(self, jobs_dir: str, data_dir: str = None):
        self.jobs_dir = jobs_dir
        self.priority_file = os.path.join(jobs_dir, "priority.json")
        self.lock = threading.Lock()
        
        # all_locations.json 路径
        if data_dir:
            self.all_locations_file = os.path.join(data_dir, "all_locations.json")
        else:
            # 默认在 jobs_dir 的兄弟目录 datas/ 下
            self.all_locations_file = os.path.join(os.path.dirname(jobs_dir), "datas", "all_locations.json")
        
        # 缓存优先城市列表
        self.priority_codes = self._load_priority()
        # 缓存所有6位区县代码
        self._all_district_codes = None
        
        # 任务文件内容缓存: path -> (mtime, data)
        self._job_cache = {}
    
    def _load_priority(self) -> List[str]:
        """加载优先城市列表"""
        if os.path.exists(self.priority_file):
            try:
                with open(self.priority_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return []
    
    def _get_all_district_codes(self) -> List[str]:
        """从 all_locations.json 提取所有6位区县代码（带缓存）"""
        if self._all_district_codes is not None:
            return self._all_district_codes
        
        codes = []
        if not os.path.exists(self.all_locations_file):
            print(f"[JobManager] WARNING: {self.all_locations_file} not found")
            self._all_district_codes = codes
            return codes
        
        try:
            with open(self.all_locations_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            def extract_codes(nodes):
                for node in nodes:
                    code = node.get("code", "")
                    if len(code) == 6:
                        codes.append(code)
                    children = node.get("children", [])
                    if children:
                        extract_codes(children)
            
            extract_codes(data)
            print(f"[JobManager] 加载了 {len(codes)} 个6位区县代码")
        except Exception as e:
            print(f"[JobManager] Error loading all_locations: {e}")
        
        self._all_district_codes = codes
        return codes
    
    def _get_known_location_codes(self) -> set:
        """扫描所有job文件，获取已知（已创建过任务）的地区代码集合"""
        known = set()
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith('.json') or filename == 'priority.json':
                continue
            file_path = os.path.join(self.jobs_dir, filename)
            data = self._load_job_file(file_path)
            for key in data.keys():
                if key != "all_done" and len(key) == 6:
                    known.add(key)
        return known

    def get_priority_codes(self) -> List[str]:
        return list(self.priority_codes)

    def get_all_location_codes(self) -> List[str]:
        return list(self._get_all_district_codes())

    def iter_task_snapshots(self) -> List[Dict]:
        snapshots: List[Dict] = []
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith('.json') or filename == 'priority.json':
                continue
            file_path = os.path.join(self.jobs_dir, filename)
            data = self._load_job_file(file_path)
            for loc_code, loc_data in data.items():
                if loc_code == "all_done":
                    continue
                for category, cat_data in loc_data.items():
                    if not isinstance(cat_data, dict):
                        continue
                    now_session_id = cat_data.get("now_session_id", "")
                    last_update_time = cat_data.get("last_update_time", "")
                    for sort_param, st_data in (cat_data.get("st_param") or {}).items():
                        if not isinstance(st_data, dict):
                            continue
                        pages = st_data.get("pages", []) or []
                        snapshots.append(
                            {
                                "location_code": loc_code,
                                "category": category,
                                "sort_param": sort_param,
                                "pages": list(pages),
                                "max_page": st_data.get("max_page", -1),
                                "is_done": bool(st_data.get("is_done", False)),
                                "need_try": bool(st_data.get("need_try", True)),
                                "dispatched_page": st_data.get("dispatched_page", 0),
                                "now_session_id": now_session_id,
                                "last_update_time": last_update_time,
                                "category_all_done": bool(cat_data.get("all_done", False)),
                            }
                        )
        return snapshots
    
    def _get_job_file(self, location_code: str) -> str:
        """根据城市代码获取对应的job文件路径"""
        prefix = location_code[:4]  # 取前4位
        return os.path.join(self.jobs_dir, f"{prefix}.json")
    
    def _load_job_file(self, file_path: str) -> Dict:
        """加载job文件 (带mtime缓存)"""
        if not os.path.exists(file_path):
            return {"all_done": False}
            
        try:
            mtime = os.path.getmtime(file_path)
            # Check cache
            if file_path in self._job_cache:
                cached_mtime, cached_data = self._job_cache[file_path]
                if cached_mtime == mtime:
                    return deepcopy(cached_data)
            
            # Cache miss or stale
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"job file must contain an object: {file_path}")
                
            self._job_cache[file_path] = (mtime, deepcopy(data))
            return data
        except (OSError, ValueError):
            self._job_cache.pop(file_path, None)
            raise
    
    def _save_job_file(self, file_path: str, data: Dict):
        """保存job文件并更新缓存"""
        try:
            content = format_job_json(data)
            
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=os.path.dirname(os.path.abspath(file_path)),
                prefix=os.path.basename(file_path) + '.', suffix='.tmp', delete=False,
            ) as f:
                temp = f.name
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, file_path)
            
            # Update cache immediately
            try:
                mtime = os.path.getmtime(file_path)
                self._job_cache[file_path] = (mtime, deepcopy(data))
            except OSError:
                self._job_cache.pop(file_path, None)
            
        except Exception as e:
            self._job_cache.pop(file_path, None)
            print(f"[JobManager] Error saving {file_path}: {e}")
            raise
    
    def _get_default_st_param_entry(self) -> Dict:
        """创建默认的st_param条目"""
        return {
            "need_try": True,
            "pages": [],
            "max_page": -1,
            "is_done": False,
            "dispatched_page": 0
        }
    
    def _get_default_category_entry(self) -> Dict:
        """创建默认的类别条目"""
        return {
            "now_session_id": "",
            "all_done": False,
            "last_update_time": "",
            "st_param": {
                st: self._get_default_st_param_entry() 
                for st in DEFAULT_ST_PARAMS
            }
        }
    
    def _ensure_location_structure(self, data: Dict, location_code: str, category: str):
        """确保数据结构中存在指定的位置和类别"""
        if location_code not in data:
            data[location_code] = {}
        
        if category not in data[location_code]:
            data[location_code][category] = self._get_default_category_entry()
    
    def get_status(self) -> Dict:
        """获取所有任务的状态统计"""
        stats = {
            "total_locations": 0,
            "done_locations": 0,
            "in_progress_locations": 0,
            "pending_locations": 0,
            "priority_pending": [],
            "non_priority_pending": []
        }
        
        # 扫描所有job文件
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith('.json') or filename == 'priority.json':
                continue
            
            file_path = os.path.join(self.jobs_dir, filename)
            data = self._load_job_file(file_path)
            
            for loc_code, loc_data in data.items():
                if loc_code == "all_done":
                    continue
                
                stats["total_locations"] += 1
                
                # 检查该城市是否完成
                all_done = True
                has_activity = False
                
                for cat_code, cat_data in loc_data.items():
                    if isinstance(cat_data, dict):
                        if cat_data.get("now_session_id"):
                            has_activity = True
                        if not cat_data.get("all_done", False):
                            all_done = False
                
                if all_done:
                    stats["done_locations"] += 1
                elif has_activity:
                    stats["in_progress_locations"] += 1
                else:
                    stats["pending_locations"] += 1
                    if loc_code in self.priority_codes:
                        stats["priority_pending"].append(loc_code)
                    else:
                        stats["non_priority_pending"].append(loc_code)
        
        return stats
    
    def get_next_job(self, session_id: str) -> Optional[Dict]:
        """
        为指定session分配下一个任务
        
        返回格式:
        {
            "location_code": "440111",
            "category": "50025969",
            "st_param": "2",
            "page": 1,
            "url": "https://sf.taobao.com/list/...",
            "desc": "Sniff-440111-Res-S2-P1"
        }
        """
        with self.lock:
            # 1. 优先检查是否有该session已经在处理的任务
            existing = self._find_session_task(session_id)
            if existing:
                return existing
            
            # 2. 优先从priority列表中分配
            for loc_code in self.priority_codes:
                task = self._try_assign_location(session_id, loc_code)
                if task:
                    return task
            
            # 3. 扫描所有job文件找未完成任务
            for filename in os.listdir(self.jobs_dir):
                if not filename.endswith('.json') or filename == 'priority.json':
                    continue
                
                file_path = os.path.join(self.jobs_dir, filename)
                data = self._load_job_file(file_path)
                
                for loc_code in data.keys():
                    if loc_code == "all_done":
                        continue
                    if loc_code in self.priority_codes:
                        continue  # 已在上面处理过
                    
                    task = self._try_assign_location(session_id, loc_code)
                    if task:
                        return task
            
            # 4. 优先地区和已有job文件都处理完了，从全量地区中随机选一个未嗅探的
            import random
            all_codes = self._get_all_district_codes()
            known_codes = self._get_known_location_codes()
            unknown_codes = [c for c in all_codes if c not in known_codes]
            
            if unknown_codes:
                random_code = random.choice(unknown_codes)
                print(f"[JobManager] 随机选取未嗅探地区: {random_code} (剩余 {len(unknown_codes)} 个)")
                task = self._try_assign_location(session_id, random_code)
                if task:
                    return task
            
            return None
    
    def _find_session_task(self, session_id: str) -> Optional[Dict]:
        """查找该session当前正在处理的任务"""
        for filename in os.listdir(self.jobs_dir):
            if not filename.endswith('.json') or filename == 'priority.json':
                continue
            
            file_path = os.path.join(self.jobs_dir, filename)
            data = self._load_job_file(file_path)
            modified = False
            
            for loc_code, loc_data in data.items():
                if loc_code == "all_done":
                    continue
                
                for cat_code, cat_data in loc_data.items():
                    if not isinstance(cat_data, dict):
                        continue
                    if cat_data.get("now_session_id") == session_id:
                        # 已完成的类别直接释放session
                        if cat_data.get("all_done"):
                            cat_data["now_session_id"] = ""
                            modified = True
                            continue
                        
                        # === 剪枝检查 ===
                        # 如果 st_param=2 已完成且 max_page < 83，标记全部完成
                        st2_data = cat_data.get("st_param", {}).get("2", {})
                        if st2_data.get("is_done", False):
                            st2_max_page = st2_data.get("max_page", -1)
                            if st2_max_page > 0 and st2_max_page < 83:
                                # 剪枝：标记所有其他 st_param 为完成
                                for other_st in ["1", "0", "3", "4", "5"]:
                                    if other_st in cat_data.get("st_param", {}):
                                        cat_data["st_param"][other_st]["is_done"] = True
                                        cat_data["st_param"][other_st]["need_try"] = False
                                cat_data["all_done"] = True
                                cat_data["now_session_id"] = ""
                                modified = True
                                print(f"[JobManager] Session pruning: {loc_code}-{cat_code} done (st2 max_page={st2_max_page} < 83)")
                                continue
                        
                        # 找到该session的任务，返回下一页
                        for st, st_data in cat_data.get("st_param", {}).items():
                            if st_data.get("is_done"):
                                continue
                            if not st_data.get("need_try", True):
                                continue
                            
                            pages = st_data.get("pages", [])
                            next_page = max(pages) + 1 if pages else 1
                            
                            if modified:
                                self._save_job_file(file_path, data)
                            
                            return self._build_task_response(
                                loc_code, cat_code, st, next_page, is_resume=True
                            )
                        
                        # 所有st_param都完成了但all_done没设置
                        all_st_done = all(
                            sd.get("is_done", False) or not sd.get("need_try", True)
                            for sd in cat_data.get("st_param", {}).values()
                        )
                        if all_st_done:
                            cat_data["all_done"] = True
                            cat_data["now_session_id"] = ""
                            modified = True
                            print(f"[JobManager] Session cleanup: {loc_code}-{cat_code} all st_params done, marking all_done")
            
            if modified:
                self._save_job_file(file_path, data)
        return None
    
    def _try_assign_location(self, session_id: str, location_code: str) -> Optional[Dict]:
        """尝试为session分配指定城市的任务
        
        严格顺序规则：
        1. 必须先完成 st_param=2 的所有页面
        2. 如果 st_param=2 在83页前完成（遇到0竞价），则跳过其他 st_param
        3. 如果 st_param=2 达到83页才完成，则需要继续做其他 st_param
        """
        file_path = self._get_job_file(location_code)
        data = self._load_job_file(file_path)
        
        # 确保结构存在
        if location_code not in data:
            data[location_code] = {}
        
        for category in DEFAULT_CATEGORIES:
            self._ensure_location_structure(data, location_code, category)
            cat_data = data[location_code][category]
            
            # 跳过已被其他session占用的
            existing_session = cat_data.get("now_session_id", "")
            if existing_session and existing_session != session_id:
                # 检查是否超时（60秒无更新）
                last_update = cat_data.get("last_update_time", "")
                if last_update:
                    try:
                        last_time = datetime.datetime.strptime(last_update, "%Y-%m-%d %H:%M:%S")
                        if (datetime.datetime.now() - last_time).total_seconds() < 60:
                            continue  # 还在活跃中，跳过
                    except:
                        pass
            
            # 跳过已完成的
            if cat_data.get("all_done"):
                continue
            
            # 严格顺序检查: 首先必须完成 st_param=2
            st2_data = cat_data.get("st_param", {}).get("2", self._get_default_st_param_entry())
            
            if not st2_data.get("is_done", False):
                # st_param=2 还未完成，必须先完成它
                st = "2"
                if st not in cat_data.get("st_param", {}):
                    cat_data["st_param"][st] = self._get_default_st_param_entry()
                st_data = cat_data["st_param"][st]
                
                pages = st_data.get("pages", [])
                next_page = max(pages) + 1 if pages else 1
                
                # 分配给该session
                cat_data["now_session_id"] = session_id
                cat_data["last_update_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st_data["dispatched_page"] = next_page
                
                self._save_job_file(file_path, data)
                
                return self._build_task_response(
                    location_code, category, st, next_page, is_resume=False
                )
            
            # st_param=2 已完成，检查是否可以剪枝
            st2_max_page = st2_data.get("max_page", -1)
            if st2_max_page > 0 and st2_max_page < 83:
                # 在83页前完成，说明遇到0竞价，可以跳过其他st_param
                # 标记所有其他 st_param 为不需要尝试且已完成
                for st in ["1", "0", "3", "4", "5"]:
                    if st in cat_data.get("st_param", {}):
                        cat_data["st_param"][st]["need_try"] = False
                        cat_data["st_param"][st]["is_done"] = True
                
                # 始终标记为全部完成（无论是否有新变更）
                cat_data["all_done"] = True
                cat_data["now_session_id"] = ""
                self._save_job_file(file_path, data)
                print(f"[JobManager] Early pruning: {location_code}-{category} done at page {st2_max_page}")
                
                continue  # 该类别已通过剪枝完成，继续下一个
            
            # st_param=2 达到83页或更多，需要继续做其他 st_param
            for st in DEFAULT_ST_PARAMS[1:]:  # 跳过 "2"，从 "1" 开始
                if st not in cat_data.get("st_param", {}):
                    cat_data["st_param"][st] = self._get_default_st_param_entry()
                
                st_data = cat_data["st_param"][st]
                
                if st_data.get("is_done"):
                    continue
                
                if not st_data.get("need_try", True):
                    continue
                
                # 找到可分配的任务
                pages = st_data.get("pages", [])
                next_page = max(pages) + 1 if pages else 1
                
                # 分配给该session
                cat_data["now_session_id"] = session_id
                cat_data["last_update_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st_data["dispatched_page"] = next_page
                
                self._save_job_file(file_path, data)
                
                return self._build_task_response(
                    location_code, category, st, next_page, is_resume=False
                )
        
        return None
    
    def _build_task_response(self, loc_code: str, category: str, st_param: str, 
                             page: int, is_resume: bool = False) -> Dict:
        """构建任务响应"""
        base_url = f"https://sf.taobao.com/list/{category}__2.htm"
        url = f"{base_url}?location_code={loc_code}&st_param={st_param}&auction_start_seg=-1&page={page}"
        
        cat_name = "Res" if category == "50025969" else "Com"
        prefix = "RESUME-" if is_resume else "Sniff-"
        
        return {
            "location_code": loc_code,
            "category": category,
            "st_param": st_param,
            "page": page,
            "url": url,
            "desc": f"{prefix}{loc_code}-{cat_name}-S{st_param}-P{page}",
            "is_resume": is_resume
        }
    
    def update_progress(self, url: str, page_num: int, has_next: bool = True, 
                       max_page: Optional[int] = None, session_id: str = "",
                       zero_bid_detected: bool = False):
        """更新任务进度
        
        zero_bid_detected: 当 st_param=2（按出价次数排序）在83页前检测到零出价时，
                          标记该 st_param 完成，并将其他 st_param 标记为不需要尝试
        """
        from urllib.parse import urlparse, parse_qs
        
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            
            loc_code = params.get('location_code', [''])[0]
            st_param = params.get('st_param', ['2'])[0]
            
            # 从路径提取category
            import re
            cat_match = re.search(r'/list/(\d+)', parsed.path)
            category = cat_match.group(1) if cat_match else "50025969"
            
            if not loc_code:
                return
            
            with self.lock:
                file_path = self._get_job_file(loc_code)
                data = self._load_job_file(file_path)
                
                self._ensure_location_structure(data, loc_code, category)
                cat_data = data[loc_code][category]
                
                if st_param not in cat_data.get("st_param", {}):
                    cat_data["st_param"][st_param] = self._get_default_st_param_entry()
                
                st_data = cat_data["st_param"][st_param]
                
                # 更新页码
                if page_num not in st_data.get("pages", []):
                    if "pages" not in st_data:
                        st_data["pages"] = []
                    st_data["pages"].append(page_num)
                
                # 更新最大页码
                if max_page and max_page > st_data.get("max_page", -1):
                    st_data["max_page"] = max_page
                
                # 更新时间戳
                cat_data["last_update_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # === 零出价剪枝逻辑 ===
                # 如果 st_param=2 在83页前检测到零出价，可以跳过其他排序方式
                if zero_bid_detected and st_param == "2" and page_num < 83:
                    print(f"[JobManager] 零出价剪枝: {loc_code}-{category}-S{st_param} 在第{page_num}页检测到零出价")
                    st_data["is_done"] = True
                    st_data["max_page"] = page_num
                    
                    # 标记其他 st_param 为不需要尝试
                    for other_st in ["1", "0", "3", "4", "5"]:
                        if other_st in cat_data.get("st_param", {}):
                            cat_data["st_param"][other_st]["need_try"] = False
                            cat_data["st_param"][other_st]["is_done"] = True
                        else:
                            cat_data["st_param"][other_st] = {
                                "need_try": False,
                                "pages": [],
                                "max_page": -1,
                                "is_done": True,
                                "dispatched_page": 0
                            }
                    
                    # 该类别完成
                    cat_data["all_done"] = True
                    cat_data["now_session_id"] = ""
                    print(f"[JobManager] 类别 {loc_code}-{category} 完成 (零出价剪枝)")
                
                # === 普通完成逻辑 ===
                elif not has_next:
                    st_data["is_done"] = True
                    st_data["max_page"] = page_num
                    
                    # 检查该类别是否全部完成
                    all_st_done = all(
                        st_data.get("is_done", False) or not st_data.get("need_try", True)
                        for st_data in cat_data.get("st_param", {}).values()
                    )
                    if all_st_done:
                        cat_data["all_done"] = True
                        cat_data["now_session_id"] = ""  # 释放session
                
                self._save_job_file(file_path, data)
                print(f"[JobManager] Updated: {loc_code}-{category}-S{st_param} page {page_num}, has_next={has_next}, zero_bid={zero_bid_detected}")
        
        except Exception as e:
            print(f"[JobManager] Error updating progress: {e}")
            raise
    
    
    def release_session(self, session_id: str):
        """释放指定session占用的任务"""
        with self.lock:
            for filename in os.listdir(self.jobs_dir):
                if not filename.endswith('.json') or filename == 'priority.json':
                    continue
                
                file_path = os.path.join(self.jobs_dir, filename)
                data = self._load_job_file(file_path)
                modified = False
                
                for loc_code, loc_data in data.items():
                    if loc_code == "all_done":
                        continue
                    
                    for cat_code, cat_data in loc_data.items():
                        if isinstance(cat_data, dict) and cat_data.get("now_session_id") == session_id:
                            cat_data["now_session_id"] = ""
                            modified = True
                
                if modified:
                    self._save_job_file(file_path, data)


# 命令行接口
if __name__ == "__main__":
    import sys
    
    jobs_dir = os.path.dirname(os.path.abspath(__file__))
    manager = JobManager(jobs_dir)
    
    if len(sys.argv) < 2:
        print("Usage: python job_manager.py <command>")
        print("Commands:")
        print("  status    - 显示任务状态统计")
        print("  next      - 获取下一个任务 (需要 session_id)")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "status":
        stats = manager.get_status()
        print(f"\n=== 任务状态统计 ===")
        print(f"总城市数: {stats['total_locations']}")
        print(f"已完成: {stats['done_locations']}")
        print(f"进行中: {stats['in_progress_locations']}")
        print(f"待处理: {stats['pending_locations']}")
        print(f"\n优先待处理: {stats['priority_pending'][:10]}...")
        print(f"普通待处理: {stats['non_priority_pending'][:10]}...")
    
    elif cmd == "next":
        session_id = sys.argv[2] if len(sys.argv) > 2 else "test_session"
        task = manager.get_next_job(session_id)
        if task:
            print(f"\n=== 分配任务 ===")
            print(json.dumps(task, ensure_ascii=False, indent=2))
        else:
            print("没有可用任务")
    
    else:
        print(f"Unknown command: {cmd}")

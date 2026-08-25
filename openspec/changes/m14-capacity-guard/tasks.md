## 1. 后端容量护栏

- [ ] 1.1 config 新增 project_limit（默认 8）与 disk_min_free_gb（默认 5），.env.example 同步占位说明
- [ ] 1.2 容量判定服务：项目计数 + shutil.disk_usage("/")，产出 accepting/reason；GET /meta/capacity 返回完整状态
- [ ] 1.3 创建项目 API 建记录前校验双护栏，超限返回 409 与原因；重索引/删除路径确认不受影响
- [ ] 1.4 测试：槽位边界（7 允许/8 拒绝）、磁盘不足 mock 拒绝、重索引放行、删除后槽位释放、capacity 接口字段完整性

## 2. 前端容量条

- [ ] 2.1 /rag 项目列表页顶部容量条（终端风：SLOTS n/8 · DISK xG free），数据来自 /rag/api/meta/capacity
- [ ] 2.2 accepting=false 时新建项目入口禁用并展示 reason；npm run build 通过

## 3. 部署与验收

- [ ] 3.1 服务器 .env 配置、部署前后端
- [ ] 3.2 线上验收：容量条显示与 df/项目数实测一致；临时调低 LIMIT=2 验证 409 与前端禁用态后恢复

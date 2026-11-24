# 深度登记 馆际复制许可簿

中型项目。文献传递岗复核历史刊号与许可条款，按页归卷并跟踪撤销。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 授权材料采信 | 查看回执和隔离原因 | `GET/POST /api/intake` | `app/intake/receive.py` `app/intake/spec.py` | `tests/test_intake.py` |
| M2 刊号与机构映射 | 查看旧刊号和机构对照 | `GET/POST /api/registry` | `app/registry/identify.py` `app/registry/rules.py` | `tests/test_registry.py` `tests/test_authority.py` |
| M3 许可版本裁决 | 查当日条款候选 | `GET/POST /api/licenses` | `app/licenses/decide.py` `app/licenses/terms.py` | `tests/test_licenses.py` |
| M4 拆页与额度占用 | 看并集、越界和退回额度 | `GET/POST /api/pages` | `app/pagination/ledger.py` `app/pagination/spans.py` | `tests/test_pages.py` |
| M5 签发请求对账 | 复算许可页与有效额度 | `GET/POST /api/balance` | `app/register/balance.py` | `tests/test_balance.py` |
| M6 批次留档复跑 | 取回原归档快照 | `POST /api/volumes` | `app/vault/record.py` `app/vault/database.py` | `tests/test_vault.py` |
| M7 许可证据签发 | 签发可复验凭证 | `POST /api/volumes/{id}/stamp` | `app/certificate/slip.py` | `tests/test_certificate.py` |
| M8 在线库归档清理 | 清理旧卷在线证据并保留可验凭证、年度额度账 | `POST /api/volumes/{id}/archive` `GET /api/archives` | `app/vault/archive.py` `app/vault/database.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 带 BOM 原件 | 流水号列无法识别 | UTF-8 带 BOM 解码 | `app/intake/spec.py` | `tests/test_intake.py::test_bom_keeps_entry` |
| TRAP-04 | 合并表重复列名 | 多一笔申请 | 记录分段并跳过 | `app/intake/receive.py` | `tests/test_intake.py::test_repeated_header_counts_segment` |
| TRAP-05 | 追加余列 | 忽略或错位 | 隔离带原列 | `app/intake/receive.py` | `tests/test_intake.py::test_extra_column_quarantines` |
| TRAP-07 | 页段短横 | 空白申请混入扣减 | 输入校验隔离 | `app/intake/form.py` | `tests/test_intake.py::test_dash_is_missing` |
| TRAP-08 | 机构号有前导零 | 馆号被误合并 | 字符串映射 | `app/registry/identify.py` | `tests/test_registry.py::test_literal_org_codes_keep_zeroes` |
| TRAP-14 | 同流水号不同页 | 随写入次序变化 | 隔离双原件 | `app/intake/receive.py` | `tests/test_intake.py::test_conflicting_copy_id_quarantines_both` |
| TRAP-19 | 专属和公开同日适用 | 高修订公开版覆盖专属 | 先比较授权范围 | `app/licenses/terms.py` | `tests/test_licenses.py::test_special_beats_public_high_revision` |
| TRAP-23 | 请求在截止日 | 到期条款多算一天 | 左闭右开 | `app/licenses/terms.py` | `tests/test_licenses.py::test_closed_at_valid_until` |
| TRAP-25 | 两版时间重叠 | 按列表顺序选版 | 高修订优先，同级冲突待证 | `app/licenses/decide.py` | `tests/test_licenses.py::test_overlapping_versions_and_tie` |
| TRAP-26 | 归档后再落印 | 证据已清空，无法重算凭证 | 已签发直接取回 `slips` 原指纹，不触碰在线证据 | `app/certificate/slip.py` | `tests/test_archive.py::test_same_incoming_does_not_revive_evidence_or_new_run` |
| TRAP-27 | 归档重试/并发 | 重复清理或写入多份归档 | 快照与清理同一事务，`INSERT ... DO NOTHING` 幂等，重试取回原记录 | `app/vault/archive.py` | `tests/test_archive.py::test_concurrent_archive_commits_once` |
| TRAP-28 | 跨卷汇总额度 | 多卷占用之和去减单卷限额出现负剩余 | 限额按卷宗窗口独立，按 占用+剩余=限额×卷宗数 对账 | `app/vault/archive.py` | `tests/test_archive.py::test_archived_annual_ledger_reconciles` |
| TRAP-29 | 旧库列约束迁移 | 只重建 volumes 导致 slips 外键指向旧表 | 关外键事务内连同 slips 一起重建 | `app/vault/database.py` | `tests/test_archive.py::test_legacy_database_migrates_and_keeps_evidence` |

58 申请页 = 32 许可页 + 18 拒绝页 + 8 待证页。C01 已许可 6 页，R01 归还 6 页，因此有效占用 26 页。申请页计在订单内部去重，各不同订单独立计数。

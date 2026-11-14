"""023 共享可观测性基座的 vendored 副本包。

权威源在 `services/common/`；本包三个模块与权威源逐字节一致，由
`scripts/check_common_sync.py`（CI）校验。修改顺序：先改权威源 → 再 cp 同步
本包 → 跑一致性脚本。禁止只改副本。
"""

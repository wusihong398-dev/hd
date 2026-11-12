# 硬盘健康卫士 Windows 构建仓库

本仓库使用 GitHub Actions 在 Windows x64 runner 上构建独立单文件 EXE。

## 当前源码状态
- 完整应用源码已放入 `bootstrap/`，以 5 个 Base64 分片保存，避免 GitHub 单文件文本接口与 ZIP 二进制上传之间的编码问题。
- 工作流会先按固定顺序重组 `source_bundle.zip`，再校验 SHA256：
  `e768adc6486a2a533c6109b6fa8a866bac31d4903f16cf565ccdfca413026e71`
- 你不需要再手动上传 `source_bundle.zip`。

## 构建流程
1. GitHub Actions 使用 Windows x64 runner 和 Python 3.11。
2. 重组并校验仓库中的源码 ZIP。
3. 下载 smartmontools 官方 GitHub Release 7.5 安装包并验证 SHA256。
4. 使用 7-Zip 提取 `smartctl.exe` 与 `drivedb.h`，不安装到系统。
5. 执行 Python 语法检查和核心单元测试。
6. 使用 PyInstaller 构建 `硬盘健康卫士.exe` 单文件。
7. 上传 `硬盘健康卫士-Windows-x64` 构建产物及 SHA256 清单。

## 下载 EXE
打开 GitHub 仓库的 Actions，进入最新成功的 `Windows EXE 构建` 运行记录，在 Artifacts 中下载 `硬盘健康卫士-Windows-x64`。

注意：当前工作流已配置并自动触发，但必须以最新 Actions 运行结果确认源码解压、测试、EXE 构建和产物上传；不能仅凭工作流文件已提交就认定 EXE 已生成。
